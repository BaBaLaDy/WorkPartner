"""WorkPartnerEngine — application facade that wires all services together.

Assembles TodoService, ScheduleService, EventBus, SessionCoordinator,
BackgroundExecutor, and shared agent graph. Uses getter injection (lambdas)
to break circular dependencies.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from src.agent.graph import create_agent
from src.agent.session import (
    BASE_SYSTEM_PROMPT,
    THINKING_PROTOCOL,
)
from src.agent.session_manager import SessionManager
from src.core.background_executor import BackgroundExecutor, ManagedSession
from src.core.session_coordinator import SessionCoordinator
from src.hub.event_bus import EventBus
from src.hub.events import AgentEvent
from src.memory import MemoryManager
from src.providers.factory import create_model, load_config
from src.providers.model_router import ModelRouter
from src.roles.loader import Role, RoleLoader
from src.mcp.manager import MCPManager
from src.services.schedule_service import ScheduleService
from src.services.todo_service import TodoService
from src.tasks.scheduler import TaskScheduler
from src.tools.cron_tools import setup_cron_tools, setup_schedule_service
from src.tools.defaults import create_default_registry
from src.tools.shutdown import is_shutdown_requested
from src.tools.todo_tools import setup_todo_service

logger = logging.getLogger(__name__)


class WorkPartnerEngine:
    """Top-level facade that assembles and coordinates all services."""

    def __init__(self):
        self.config = load_config()

        # -- Services --
        tasks_file = self.config.get("tasks", {}).get("file", "./tasks.json")
        self.todo_service = TodoService(tasks_file)

        sched_file = self.config.get("tasks", {}).get("schedules_file", "./scheduled_tasks.json")
        self.schedule_service = ScheduleService(sched_file)

        self.event_bus = EventBus()

        # -- Roles --
        roles_dir = self.config.get("roles", {}).get("directory", "./roles")
        self.role_loader = RoleLoader(roles_dir)
        self.role_loader.load_all()

        # -- Session persistence --
        history_dir = self.config.get("history", {}).get("directory", "./history")
        self.session_manager = SessionManager(history_dir)

        # -- Memory --
        memory_dir = self.config.get("memory", {}).get("dir", "./memory")
        self.memory: MemoryManager | None = None  # initialised after model_router below

        # -- Shared agent graph (created once, reused by all sessions) --
        agent_cfg = self.config.get("agent", {})
        self.model_router = ModelRouter(self.config)
        self.model = self.model_router.get_model("chat")

        # Finish memory init now that model_router is ready
        self.memory = MemoryManager(
            base_dir=memory_dir,
            model=self.model_router.get_model("utility_large"),
        )
        self.max_turns = agent_cfg.get("max_turns", 70)

        # Registry: start with basic tools first to build the agent graph,
        # then add SubAgent tools once the agent exists.
        self.registry = create_default_registry()
        self.tool_schemas = self.registry.as_openai_tools()

        self.agent = create_agent(
            model=self.model,
            registry=self.registry,
            checkpointer=self.session_manager.checkpointer,
            compression_threshold=agent_cfg.get("compression_threshold", 30),
            compression_keep_recent=agent_cfg.get("compression_keep_recent", 5),
            summary_model=self.model_router.get_model("utility_large"),
        )

        # Register SubAgent tools (need agent, session_manager, role_loader)
        from src.tools.subagent_tools import create_subagent_tools
        sub_tools = create_subagent_tools(
            self.session_manager, self.agent, self.role_loader,
            self.tool_schemas, self.max_turns, self.event_bus, self.memory,
        )
        for fn in sub_tools:
            self.registry.register(
                fn,
                read_only=False,
                requires_permission=True,
                concurrency_safe=False,
                tags=("agent", "subagent"),
            )
        # Rebuild tool_schemas to include subagent_batch
        self.tool_schemas = self.registry.as_openai_tools()

        # -- Scheduler --
        tz = self.config.get("scheduler", {}).get("timezone", "Asia/Shanghai")
        self.scheduler = TaskScheduler(
            self.schedule_service.manager,
            todo=self.todo_service.manager,
            timezone_str=tz,
        )

        # -- BackgroundExecutor (created but not started until start_background) --
        executor_cfg = self.config.get("executor", {})
        self.executor = BackgroundExecutor(
            get_todo=lambda: self.todo_service,
            get_bus=lambda: self.event_bus,
            create_managed_session=self.create_managed_session,
            get_role=self.role_loader.get,
            poll_interval=float(executor_cfg.get("poll_interval", 1800.0)),
            max_concurrent=int(executor_cfg.get("max_concurrent", 1)),
            max_retries=int(executor_cfg.get("max_retries", 3)),
        )

        # -- SessionCoordinator (memory-aware) --
        self.coordinator = SessionCoordinator(
            self.session_manager,
            get_memory=lambda: self.memory,
        )

        # -- EventBus subscriptions: write execution log on task completion --
        async def _log_event(event: AgentEvent) -> None:
            # text_delta fires once per streamed token — logging it to disk
            # synchronously on every token blocks the event loop and, under
            # concurrent SubAgents, serializes what should be parallel work.
            if event.type == "text_delta":
                return
            self.memory.append_event_log(event)

        async def _on_task_done(event: AgentEvent) -> None:
            data = event.payload
            role_name = data.get("role") or "task_agent"
            tools_used = data.get("tools_used", [])
            self.memory.append_execution_log(
                task_id=data.get("task_id", ""),
                title=data.get("title", ""),
                result="done",
                duration_sec=data.get("duration_sec", 0.0),
                tools=tools_used,
                result_summary=data.get("result_summary"),
                role=role_name,
                thread_id=data.get("session_id"),
            )
            self.memory.append_task_agent_log(
                task_id=data.get("task_id", ""),
                title=data.get("title", ""),
                role=role_name,
                strategy="managed_session",
                result="done",
                tools=tools_used,
                result_summary=data.get("result_summary"),
            )
            self.memory.append_role_log(
                role=role_name,
                task_id=data.get("task_id", ""),
                title=data.get("title", ""),
                result="done",
                tools=tools_used,
                result_summary=data.get("result_summary"),
            )
            self.memory.check_and_distill_patterns()

        async def _on_task_failed(event: AgentEvent) -> None:
            data = event.payload
            role_name = data.get("role") or "task_agent"
            tools_used = data.get("tools_used", [])
            self.memory.append_execution_log(
                task_id=data.get("task_id", ""),
                title=data.get("title", ""),
                result="failed",
                duration_sec=data.get("duration_sec", 0.0),
                tools=tools_used,
                error=data.get("error"),
                role=role_name,
                thread_id=data.get("session_id"),
            )
            self.memory.append_task_agent_log(
                task_id=data.get("task_id", ""),
                title=data.get("title", ""),
                role=role_name,
                strategy="managed_session",
                result="failed",
                tools=tools_used,
                error=data.get("error"),
            )
            self.memory.append_role_log(
                role=role_name,
                task_id=data.get("task_id", ""),
                title=data.get("title", ""),
                result="failed",
                tools=tools_used,
                error=data.get("error"),
            )

        self.event_bus.subscribe_all(_log_event)
        self.event_bus.subscribe("task.done", _on_task_done)
        self.event_bus.subscribe("task.failed", _on_task_failed)

        # -- SupervisorAgent: global observer / quality gate / daily report --
        from src.core.supervisor_agent import SupervisorAgent
        self.supervisor = SupervisorAgent(self)

        # Task 4: wire daily report cron trigger from APScheduler
        sup_cfg = self.config.get("supervisor", {})
        if sup_cfg.get("enabled", False) and sup_cfg.get("daily_report_time"):
            self._register_supervisor_cron(sup_cfg["daily_report_time"])

        # -- BridgeManager (lazy — not started until connect_channel) --
        from src.im_bridge.bridge import BridgeManager
        self.bridge = BridgeManager()
        im_cfg = self.config.get("im_bridge", {})
        self._adapters_config = im_cfg.get("adapters", {})

        # -- Skills --
        skills_dir = self.config.get("skills", {}).get("directory", "./skills")
        from src.skills.loader import SkillLoader
        from src.skills.injector import SkillInjector
        self.skill_loader = SkillLoader(skills_dir)
        self.skill_loader.load_all()
        self.skill_injector = SkillInjector(self.skill_loader)

        # -- MCP manager (shared across all sessions) --
        mcp_cfg = self.config.get("mcp", {})
        self.mcp = MCPManager(
            self.registry,
            history_dir=history_dir,
            tool_prefix=mcp_cfg.get("tool_prefix", "mcp"),
        )
        self._mcp_auto_connect = mcp_cfg.get("auto_connect", True)

        self._running = False

    def wakeup_executor(self, reason: str = "manual") -> dict[str, Any]:
        """Request the background executor to check pending tasks immediately."""
        status = self.executor.wake_up(reason=reason)
        return status

    def _register_supervisor_cron(self, time_str: str) -> None:
        """Register supervisor daily report and weekly memory maintenance crons."""
        try:
            hour, minute = time_str.split(":")
            self.scheduler._scheduler.add_job(
                self.supervisor.daily_report,
                trigger="cron",
                hour=int(hour),
                minute=int(minute),
                id="supervisor_daily_report",
                replace_existing=True,
                name="大管家每日日报",
            )
            logger.info("Supervisor daily report registered at %s", time_str)
        except Exception:
            logger.warning("Failed to register supervisor daily report at %s", time_str, exc_info=True)

        # Weekly memory maintenance — every Monday at 02:00
        try:
            import asyncio as _asyncio

            def _run_maintenance():
                loop = _asyncio.new_event_loop()
                try:
                    loop.run_until_complete(self.supervisor.memory_maintenance())
                finally:
                    loop.close()

            self.scheduler._scheduler.add_job(
                _run_maintenance,
                trigger="cron",
                day_of_week="mon",
                hour=2,
                minute=0,
                id="supervisor_weekly_maintenance",
                replace_existing=True,
                name="大管家每周记忆维护",
            )
            logger.info("Supervisor weekly maintenance registered (Mon 02:00)")
        except Exception:
            logger.warning("Failed to register supervisor weekly maintenance", exc_info=True)

    def executor_status(self) -> dict[str, Any]:
        """Return current background executor status for the API/UI."""
        return self.executor.status()

    # -- Managed session factory (called by BackgroundExecutor) --

    async def create_managed_session(
        self, task_id: str, title: str, description: str,
        role: Role | None = None,
    ) -> ManagedSession:
        """Create a managed session for a single task execution.

        Uses the shared agent graph, creates a new thread for isolation.
        If role is provided, its prompt is injected and tools are filtered.
        """
        thread_id = self.session_manager.create_session(
            name=f"task-{title[:30]}",
            session_type="managed",
            owner="scheduler",
        )

        thread_config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self.max_turns,
        }

        # Fall back to task_agent role when none is specified
        if role is None:
            role = self.role_loader.get("task_agent")

        # System prompt — use PromptAssembler for standard sections
        from src.agent.prompt import PromptAssembler
        assembler = PromptAssembler()

        roster = self.role_loader.list_roles()
        team_delegation = ""
        if roster:
            roster_lines = [
                f"- {r.name} ({r.display_name}): {r.description}"
                for r in roster
            ]
            example_tasks = ", ".join(
                "{"
                f"'title':'{r.display_name}任务',"
                "'description':'...',"
                f"'role':'{r.name}'"
                "}"
                for r in roster[:3]
            )
            team_delegation = (
                "## Team delegation\n"
                "When using subagent_batch, put all independent role tasks in one call. "
                "Use only these role ids or display names in tasks[i].role; do not write free-form role prompts. "
                f"For example: tasks=[{example_tasks}].\n"
                + "\n".join(roster_lines)
            )

        system_prompt = assembler.assemble(
            profile="managed",
            role=role,
            base_rules=BASE_SYSTEM_PROMPT + THINKING_PROTOCOL,
            team_delegation=team_delegation,
            memory_manager=self.memory,
            session_type="task_agent",
        )
        system_prompt += f"\n\nYou are executing a scheduled task: {title}"

        # Inject memory for managed sessions
        memory_section = self.memory.assemble_memory(session_type="task_agent")
        if memory_section:
            system_prompt += (
                "\n\n**执行前**：如 <memory> 中存在与此任务类型匹配的操作模式，"
                "优先遵循其工具链和策略，跳过已知失败路径。"
            )
        if role is not None:
            role_memory = self.memory.assemble_role_memory(role.name)
            if role_memory:
                system_prompt += "\n\n" + role_memory

        # Tool filtering: if role specifies tools_override, filter
        tools = self.tool_schemas
        if role is not None and role.tools_override is not None:
            allowed = set(role.tools_override)
            tools = [t for t in tools if t["function"]["name"] in allowed]

        session = ManagedSession(
            thread_id=thread_id,
            agent=self.agent,
            config=thread_config,
            system_prompt=system_prompt,
            tools=tools,
        )
        return session

    # -- Interactive session creation (shared graph) --

    def create_interactive_session(
        self,
        owner: str = "ui",
        role: Role | None = None,
    ) -> "AgentSession":
        """Create an interactive session sharing the engine's graph/registry/memory.

        Unlike ManagedSession (background tasks), this session is for
        direct user interaction — CLI, Web UI, IM bridge.
        """
        from src.agent.session import AgentSession

        session = AgentSession(
            session_manager=self.session_manager,
            todo_service=self.todo_service,
            model_router=self.model_router,
            session_type="interactive",
            owner=owner,
            workspace_scope="",
            permission_mode="operate",
            memory_manager=self.memory,
            role=role,
            # Share engine components
            agent=self.agent,
            registry=self.registry,
            tool_schemas=self.tool_schemas,
            injector=self.skill_injector,
        )
        return session

    def create_supervisor_session(self) -> "AgentSession":
        """Create (or reuse) an interactive session for chatting with the supervisor.

        The returned session should be used with stream_events(..., thread_id=engine.supervisor.thread_id)
        so conversation history persists on the supervisor's fixed thread.
        """
        from src.agent.session import AgentSession

        if hasattr(self, "_supervisor_session") and self._supervisor_session is not None:
            return self._supervisor_session

        session = AgentSession(
            session_manager=self.session_manager,
            todo_service=self.todo_service,
            model_router=self.model_router,
            session_type="supervisor",
            owner="supervisor",
            workspace_scope="",
            permission_mode="operate",
            memory_manager=self.memory,
            role=None,
            agent=self.agent,
            registry=self.registry,
            tool_schemas=self.tool_schemas,
            injector=self.skill_injector,
        )
        self._supervisor_session = session
        return session

    def build_supervisor_system_prompt(self, user_message: str = "") -> str:
        """Build a fresh supervisor system prompt with current task dashboard + global memory."""
        from collections import Counter
        from src.agent.prompt import PromptAssembler

        tasks = self.todo_service.list()
        counts = Counter(t.get("status", "unknown") for t in tasks)
        learning_highlights = self.supervisor.learning_highlights()
        dashboard = (
            f"当前任务看板：待处理 {counts.get('pending', 0)} 个，"
            f"进行中 {counts.get('in_progress', 0)} 个，"
            f"已完成 {counts.get('done', 0)} 个。"
        )
        learning_block = ""
        if learning_highlights:
            lines = [
                f"- {item['role']}: 擅长 {item['task_type']} | confidence={item['confidence']} | tools={item['tools_chain']}"
                for item in learning_highlights
            ]
            learning_block = "最近学到的调度经验：\n" + "\n".join(lines) + "\n"

        supervisor_rules = (
            "# 大管家 (Supervisor)\n\n"
            "你是 WorkPartner 的大管家，负责全局观察和协调。你的职责：\n"
            "- 回答用户关于「今天做了什么」、「哪些任务失败了」、「团队现在状态如何」等问题\n"
            "- 从注入的记忆（daily_log、action_items、insights）中检索信息回答\n"
            "- 用简洁、有温度的语气汇报工作进展\n"
            "- 不要假装在执行任务，你的角色是汇报和协调\n\n"
            f"{dashboard}\n"
            f"{learning_block}"
        )

        assembler = PromptAssembler()
        system_prompt = assembler.assemble(
            profile="supervisor",
            supervisor_rules=supervisor_rules,
            memory_manager=self.memory,
            user_message=user_message,
            injector=self.skill_injector,
        )
        return system_prompt

    # -- MCP lifecycle --

    async def start_mcp(self) -> None:
        """Start MCP connections. Used by CLI path.

        API/Daemon path: MCP is managed per-session (AgentSession.start_mcp).
        """
        await self._start_mcp()

    async def _start_mcp(self) -> None:
        """Internal: start MCP on the engine's registry."""
        await self.mcp.start()

    async def stop_mcp(self) -> None:
        """Shut down MCP connections."""
        await self.mcp.stop()

    # -- IM Channel management --

    async def connect_channel(self, name: str) -> bool:
        """Connect a single IM channel (feishu, telegram, etc.).

        Creates a bridge AgentSession if not already present.
        """
        from src.agent.session import AgentSession

        # Ensure bridge has an AgentSession
        if self.bridge._agent_session is None:
            self.bridge._agent_session = self.create_interactive_session(owner="bridge")
            await self.bridge._agent_session.start_mcp()

        cfg = self._adapters_config.get(name, {})
        if not cfg:
            logger.warning("No config for adapter '%s'", name)
            return False

        return await self.bridge.connect_adapter(name, cfg)

    async def disconnect_channel(self, name: str) -> bool:
        """Disconnect a single IM channel."""
        return await self.bridge.disconnect_adapter(name)

    def list_channels(self) -> list[dict]:
        """Return status of all configured channels."""
        return self.bridge.list_adapters()

    # -- Lifecycle --

    def start_background(self):
        """Start the scheduler and background executor."""
        self._running = True
        self.scheduler.start()
        setup_cron_tools(self.scheduler)
        setup_schedule_service(self.schedule_service)
        setup_todo_service(self.todo_service)
        logger.info("WorkPartnerEngine: background services started")

    async def start_async(self):
        """Async entry point — starts BackgroundExecutor loop."""
        await self.executor.start()

    async def stop(self):
        """Gracefully shut down all services.

        Safe to call from any event loop. If called from a different loop
        than the executor's, only sets the shutdown flag without awaiting
        — the owning loop handles actual cleanup.
        """
        self._running = False

        if self.executor._task is not None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None and self.executor._task.get_loop() is loop:
                await self.executor.stop()
            else:
                # Cross-loop call: just cancel, owning loop handles cleanup
                self.executor._task.cancel()

        try:
            self.scheduler.shutdown(wait=False)
        except Exception as exc:
            if exc.__class__.__name__ != "SchedulerNotRunningError":
                raise
        logger.info("WorkPartnerEngine: stopped")

    # -- Convenience: unified serve entry point --

    def run_serve(self, with_api: bool = True, host: str = "0.0.0.0",
                  port: int = 8000, dev_mode: bool = True,
                  on_shutdown=None, with_bridge: bool = False):
        """Run the engine as a persistent process.

        Args:
            with_api: If True, start FastAPI server alongside the executor.
                      If False, run executor only (equivalent to old --daemon).
            host: API bind address (only when with_api=True).
            port: API port (only when with_api=True).
            dev_mode: Enable CORS and debug logging (only when with_api=True).
            on_shutdown: Optional callback called after the engine has fully
                         stopped. Useful for cleaning up external processes.
            with_bridge: If True, start IM bridge (Telegram, Feishu, etc.)
                         alongside the engine using a dedicated AgentSession.
        """
        from src.api.server import create_uvicorn_server

        self.start_background()

        # On Windows, the default ProactorEventLoop has a known bug:
        # _ProactorBaseWritePipeTransport._loop_writing can assert-fail when
        # subprocess pipes produce rapid output. SelectorEventLoop avoids this.
        import sys
        if sys.platform == "win32":
            try:
                asyncio.set_event_loop_policy(
                    asyncio.WindowsSelectorEventLoopPolicy()
                )
            except Exception:
                pass

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        api_server = None
        api_thread = None

        if with_api:
            api_server = create_uvicorn_server(
                self, host=host, port=port, dev_mode=dev_mode,
                skip_lifespan_startup=True,
            )
            api_thread = threading.Thread(
                target=api_server.run,
                name="workpartner-api",
                daemon=True,
            )
            api_thread.start()
            logger.info("API server thread started on %s:%d", host, port)

        mode = "serve (with API)" if with_api else "daemon (no API)"

        async def _run():
            if with_bridge:
                if self.bridge._adapters:
                    logger.info("IM Bridge started with %d adapter(s)", len(self.bridge._adapters))
                else:
                    logger.warning("IM Bridge: no adapters connected (check config + tokens)")

            await self.start_async()
            logger.info("%s running. Press Ctrl+C to stop.", mode)
            try:
                # Sleep indefinitely — KeyboardInterrupt will break us out
                while True:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass

            if api_server is not None:
                logger.info("API server stopping...")
                api_server.should_exit = True

            if with_bridge:
                logger.info("IM Bridge stopping...")
                await self.bridge.stop()

            await self.stop()

        main_task = loop.create_task(_run())
        try:
            loop.run_until_complete(main_task)
        except KeyboardInterrupt:
            logger.info("Received Ctrl+C, stopping…")
            if not main_task.done():
                main_task.cancel()
            try:
                loop.run_until_complete(main_task)
            except (asyncio.CancelledError, KeyboardInterrupt):
                pass
        # Cleanup: cancel all remaining tasks and close the loop
        for task in asyncio.all_tasks(loop):
            if task is not main_task and not task.done():
                task.cancel()
        # Use a timeout so we don't hang forever waiting for tasks
        loop.run_until_complete(asyncio.gather(
            *asyncio.all_tasks(loop), return_exceptions=True
        ))
        loop.close()
        if api_thread is not None and api_thread.is_alive():
            api_thread.join(timeout=5.0)
            if api_thread.is_alive():
                logger.warning("API server thread did not stop within timeout")
        logger.info("Engine %s stopped", mode)
        if on_shutdown is not None:
            on_shutdown()

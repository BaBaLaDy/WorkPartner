"""BackgroundExecutor — async todo polling and task execution.

Runs an async loop: watch_todos() → pick pending → create managed session →
execute via agent graph → update status → broadcast events.

Concurrency limited by asyncio.Semaphore (default 3 parallel tasks).
Failed tasks retry with exponential backoff (1s, 2s, 4s), max 3 attempts.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Coroutine

if TYPE_CHECKING:
    from src.roles.loader import Role
    from src.services.todo_service import TodoService
    from src.hub.event_bus import EventBus

logger = logging.getLogger(__name__)

# Factory type: takes (task_id, title, description, role) → returns a ManagedSession handle
ManagedSessionFactory = Callable[
    [str, str, str, "Role | None"],
    Coroutine[None, None, "ManagedSession"],
]


class ManagedSession:
    """Handle returned by the Engine's managed-session factory.

    Encapsulates everything needed to run one task: thread_id, agent, config.
    """

    def __init__(self, thread_id: str, agent: Any, config: dict,
                 system_prompt: str, tools: list | None = None):
        self.thread_id = thread_id
        self.agent = agent
        self.config = config
        self.system_prompt = system_prompt
        self.tools = tools

    async def run(self, task_prompt: str, event_bus: Any | None = None,
                  task_id: str = "") -> str:
        """Execute the agent on the task prompt, return response text.

        If event_bus and task_id are provided, intermediate events (tool calls,
        text deltas) are emitted for real-time UI display.
        Sets self.tools_used to the list of tool names invoked during execution.
        """
        from langchain_core.messages import HumanMessage

        self.tools_used: list[str] = []
        response_parts = []
        stream = self.agent.astream_events(
            {
                "messages": [HumanMessage(content=task_prompt)],
                "system_prompt": self.system_prompt,
                "tools": self.tools,
                "session_type": "managed",
                "owner": "scheduler",
                "workspace_scope": "",
                "permission_mode": "operate",
                "task_id": task_id or None,
                "parent_schedule_id": None,
                "run_status": "running",
                "failure_count": 0,
                "last_tool_summary": "",
            },
            config=self.config,
            version="v2",
        )

        async for event in stream:
            kind = event.get("event", "")
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    response_parts.append(chunk.content)
                    if event_bus and task_id:
                        await event_bus.emit(
                            "text_delta",
                            {"task_id": task_id, "text": chunk.content},
                            caller="managed_session",
                            agent_id="task_agent",
                        )
            elif kind == "on_tool_start":
                tool_name = event.get("name", "")
                if tool_name:
                    self.tools_used.append(tool_name)
                if event_bus and task_id:
                    tool_input = event.get("data", {}).get("input", "")
                    await event_bus.emit(
                        "tool_start",
                        {"task_id": task_id, "tool": tool_name, "input": str(tool_input)[:200]},
                        caller="managed_session",
                        agent_id="task_agent",
                    )
            elif kind == "on_tool_end" and event_bus and task_id:
                tool_name = event.get("name", "")
                await event_bus.emit(
                    "tool_end",
                    {"task_id": task_id, "tool": tool_name},
                    caller="managed_session",
                    agent_id="task_agent",
                )

        return "".join(response_parts) if response_parts else "(no output)"


class BackgroundExecutor:
    """Background async loop that processes pending todos.

    Design: uses getter injection (get_todo, get_bus) and a
    create_managed_session factory provided by the Engine to avoid
    circular dependencies and duplicated agent graph creation.
    """

    def __init__(
        self,
        get_todo: Callable[[], Any],
        get_bus: Callable[[], Any],
        create_managed_session: ManagedSessionFactory,
        get_role: Callable[[str], "Role | None"] | None = None,
        poll_interval: float = 5.0,
        max_concurrent: int = 3,
        max_retries: int = 3,
    ):
        self._get_todo = get_todo
        self._get_bus = get_bus
        self._create_managed_session = create_managed_session
        self._get_role = get_role
        self._poll_interval = poll_interval
        self._max_concurrent = max_concurrent
        self._max_retries = max_retries
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running = False
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake_event: asyncio.Event | None = None
        self._wake_requested = False
        # Track running asyncio tasks by task_id for cancellation
        self._running_tasks: dict[str, asyncio.Task] = {}

    # -- Lifecycle --

    async def start(self):
        """Start the background execution loop."""
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._wake_event = asyncio.Event()
        if self._wake_requested:
            self._wake_event.set()
        self._task = asyncio.create_task(self.watch_todos())
        logger.info("BackgroundExecutor started (concurrency=%d, poll=%.1fs)",
                     self._max_concurrent, self._poll_interval)

    async def stop(self):
        """Stop the background execution loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        active_tasks = [
            task for task in self._running_tasks.values()
            if not task.done()
        ]
        for task in active_tasks:
            task.cancel()
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        self._running_tasks.clear()
        logger.info("BackgroundExecutor stopped")

    def wake_up(self, reason: str = "manual") -> dict[str, Any]:
        """Wake the polling loop from any thread.

        FastAPI may run in a different thread from the executor loop, so the
        event must be set with call_soon_threadsafe when a loop is available.
        """
        self._wake_requested = True
        if self._loop is not None and self._wake_event is not None:
            self._loop.call_soon_threadsafe(self._wake_event.set)
        logger.info("BackgroundExecutor wake requested (%s)", reason)
        return self.status()

    async def trigger_execution(self, reason: str = "manual") -> dict[str, Any]:
        """Async API-friendly wrapper for wake_up()."""
        return self.wake_up(reason=reason)

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "poll_interval": self._poll_interval,
            "max_concurrent": self._max_concurrent,
            "active_tasks": list(self._running_tasks.keys()),
            "active_count": len(self._running_tasks),
            "wake_requested": self._wake_requested,
        }

    # -- Main loop --

    async def watch_todos(self):
        """Poll TodoService for pending tasks and execute them."""
        while self._running:
            try:
                self._wake_requested = False
                todo = self._get_todo()
                task = todo.get_next_pending()
                if task is not None:
                    bus = self._get_bus()
                    await bus.emit("task.added", {
                        "task_id": task["id"],
                        "task_title": task.get("title", ""),
                        "detected_at": datetime.now(timezone.utc).isoformat(),
                    })
                    await self._semaphore.acquire()
                    exec_task = asyncio.create_task(self._execute_task(task))
                    self._running_tasks[task["id"]] = exec_task
                    exec_task.add_done_callback(
                        lambda t, tid=task["id"]: self._running_tasks.pop(tid, None)
                    )
            except Exception:
                logger.exception("Error in watch_todos loop")
            await self._wait_for_next_check()

    async def _wait_for_next_check(self) -> None:
        if self._wake_event is None:
            await asyncio.sleep(self._poll_interval)
            return
        try:
            await asyncio.wait_for(self._wake_event.wait(), timeout=self._poll_interval)
        except asyncio.TimeoutError:
            return
        finally:
            self._wake_event.clear()

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task. Returns False if task not found."""
        running = self._running_tasks.get(task_id)
        if running and not running.done():
            running.cancel()
            logger.info("Cancelled running task [%s]", task_id)
            return True
        return False

    # -- Task execution --

    async def _execute_task(self, task: dict):
        """Execute a single todo task with retry logic."""
        task_id = task["id"]
        title = task["title"]
        description = task.get("description", "")
        failure_count = 0
        task_start_time = datetime.now(timezone.utc)

        while self._running:
            session_thread_id: str | None = None
            try:
                # Check if user cancelled this task
                todo = self._get_todo()
                current = todo.get(task_id)
                if current and current.get("status") == "cancelled":
                    logger.info("Task [%s] was cancelled by user, skipping", task_id)
                    return

                todo.mark_in_progress(task_id)

                # Resolve role from task
                role_name = task.get("role")
                role = self._get_role(role_name) if (self._get_role and role_name) else None

                # Create managed session and store thread_id in task
                session = await self._create_managed_session(task_id, title, description, role)
                session_thread_id = session.thread_id
                todo.update(task_id, session_thread_id=session_thread_id)

                bus = self._get_bus()
                await bus.emit("task.started", {
                    "task_id": task_id, "title": title,
                    "session_id": session_thread_id,
                    "status": "in_progress",
                    "role": role_name or "task_agent",
                    "actor": role.display_name if role else "沈衡",
                })

                # Execute
                start_time = datetime.now(timezone.utc)
                result = await self._run_session(session, task_id, title, description, bus)
                duration_sec = (datetime.now(timezone.utc) - start_time).total_seconds()

                # Mark done
                result_summary = result[:200] if result and result != "(no output)" else None
                todo.mark_done(task_id)
                await bus.emit("task.done", {
                    "task_id": task_id, "title": title, "result": result,
                    "status": "done",
                    "session_thread_id": session.thread_id,
                    "role": role_name or "task_agent",
                    "actor": role.display_name if role else "沈衡",
                    "result_summary": result_summary,
                    "tools_used": getattr(session, "tools_used", []),
                    "duration_sec": duration_sec,
                })
                logger.info("Task completed: [%s] %s", task_id, title)
                return

            except asyncio.CancelledError:
                # Task was cancelled mid-execution
                todo = self._get_todo()
                current = todo.get(task_id)
                if current and current.get("status") != "cancelled":
                    todo.mark_cancelled(task_id)
                await self._get_bus().emit("task.cancelled", {
                    "task_id": task_id, "title": title,
                    "status": "cancelled",
                    "role": task.get("role") or "default",
                })
                logger.info("Task [%s] cancelled mid-execution", task_id)
                return

            except Exception as e:
                failure_count += 1
                logger.warning(
                    "Task [%s] failed (attempt %d/%d): %s",
                    task_id, failure_count, self._max_retries, e,
                )

                if failure_count >= self._max_retries:
                    # Mark permanently failed
                    duration_sec = (datetime.now(timezone.utc) - task_start_time).total_seconds()
                    todo = self._get_todo()
                    todo.mark_failed(task_id)
                    bus = self._get_bus()
                    await bus.emit("task.failed", {
                        "task_id": task_id, "title": title,
                        "status": "done",
                        "session_thread_id": session_thread_id,
                        "role": task.get("role") or "default",
                        "error": str(e), "failure_count": failure_count,
                        "duration_sec": duration_sec,
                        "tools_used": [],
                    })
                    logger.error(
                        "Task [%s] failed permanently after %d attempts",
                        task_id, failure_count,
                    )
                    return

                # Exponential backoff before retry
                backoff = 2 ** (failure_count - 1)  # 1s, 2s, 4s
                bus = self._get_bus()
                await bus.emit("task.retrying", {
                    "task_id": task_id, "attempt": failure_count,
                })
                await asyncio.sleep(backoff)
            finally:
                self._semaphore.release()

    async def _run_session(
        self, session: "ManagedSession", task_id: str, title: str, description: str,
        event_bus: Any = None,
    ) -> str:
        """Execute the session via the Engine factory, return result text."""
        task_prompt = (
            f"Complete this task:\n\n"
            f"**Title**: {title}\n"
            f"**Description**: {description or '(no description)'}\n\n"
            f"Use your tools to complete it. Be concise."
        )
        result = await session.run(task_prompt, event_bus=event_bus, task_id=task_id)
        return result

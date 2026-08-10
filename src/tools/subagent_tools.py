"""SubAgent tools — allow the agent to spawn parallel sub-agents.

Only `subagent_batch` is exposed. The agent can pass 1-N tasks (capped at
SUBLIMIT_BATCH); each task runs in an isolated ManagedSession with its own
thread_id, system prompt, and filtered tool set.

Usage in the engine:
    tools = create_subagent_tools(
        session_manager, agent, role_loader, base_tool_schemas, max_turns,
    )
    for fn in tools:
        registry.register(fn)
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.agent.session import THINKING_PROTOCOL
from src.hub.event_bus import EventBus
from src.roles.loader import build_role_presence

# Maximum number of SubAgents that can run in parallel within a single call.
SUBAGENT_BATCH_LIMIT = 5
# Independent of SUBAGENT_BATCH_LIMIT: caps how many SubAgent LLM calls run at
# once *globally*. Set above SUBAGENT_BATCH_LIMIT so a single subagent_batch
# call's own 1-5 tasks are never throttled against each other (that would
# silently cap the advertised "up to 5 concurrent" and mask whether the
# underlying I/O fixes actually improved concurrency) — it only kicks in when
# background tasks stack on top of an in-flight batch.
_SUBAGENT_SEMAPHORE = asyncio.Semaphore(8)
# Blocked tools — SubAgents must never be able to call these.
SUBAGENT_BLOCKED_TOOLS = {"subagent_batch", "shutdown_agent"}

_SUBAGENT_RULES = (
    "You are a SubAgent — a delegated task executor with isolated context.\n\n"
    "Rules:\n"
    "- Be concise. If a tool fails, try a different approach. Fail 3+ times → report the error.\n"
    "- Do NOT attempt to create additional sub-agents.\n"
)


async def _run_with_semaphore(coro):
    async with _SUBAGENT_SEMAPHORE:
        return await coro


def _build_subagent_prompt(
    title: str, description: str, role_system_prompt: str | None,
    role_presence: str = "",
    role_memory: str = "",
) -> str:
    """Build a lightweight system prompt for a single SubAgent session.

    Delegates to PromptAssembler for consistent section ordering.
    """
    from src.agent.prompt import PromptAssembler
    assembler = PromptAssembler()
    system_prompt = assembler.assemble(
        profile="subagent",
        subagent_rules=_SUBAGENT_RULES,
        thinking_protocol=THINKING_PROTOCOL,
    )
    if role_system_prompt is not None:
        system_prompt = f"# Role: {role_system_prompt}\n\n" + system_prompt
    if role_presence:
        system_prompt += "\n\n## Role presence\n" + role_presence
    if role_memory:
        system_prompt += "\n\n" + role_memory
    system_prompt += (
        f"\n\nTask: {title}\n"
        f"Description: {description or '(no description)'}\n\n"
        "Use your available tools to complete this task."
    )
    return system_prompt


def _filter_tools(tool_schemas: list[dict], extra_blocked: set[str] | None = None) -> list[dict]:
    """Return a filtered list of tool schemas with blocked tools removed."""
    blocked = set(SUBAGENT_BLOCKED_TOOLS)
    if extra_blocked:
        blocked |= extra_blocked
    return [t for t in tool_schemas if t["function"]["name"] not in blocked]


def _resolve_role(
    role_name: str | None, role_loader: Any,
) -> Any | None:
    if role_name is None:
        return None
    role_obj = role_loader.get(role_name)
    if role_obj is not None:
        return role_obj
    for candidate in role_loader.list_roles():
        if role_name in {candidate.display_name, candidate.name}:
            return candidate
    return None


def _available_roles(role_loader: Any) -> str:
    roles = role_loader.list_roles()
    return ", ".join(f"{r.name} ({r.display_name})" for r in roles)


def _role_schema_values(role_loader: Any) -> list[str]:
    values: list[str] = []
    for role in role_loader.list_roles():
        for value in (role.name, role.display_name):
            if value and value not in values:
                values.append(value)
    return values


def _role_schema_summary(role_loader: Any) -> str:
    roles = role_loader.list_roles()
    if not roles:
        return "No roles are loaded."
    return "; ".join(
        f"{role.name} ({role.display_name}): {role.description}"
        for role in roles
    )


def _infer_role_name(task_desc: dict, role_loader: Any) -> str | None:
    haystack = f"{task_desc.get('title', '')}\n{task_desc.get('description', '')}"
    for role in role_loader.list_roles():
        if role.display_name and role.display_name in haystack:
            return role.name
        if role.name and role.name in haystack:
            return role.name
    return None


def _build_subagent_batch_schema(role_loader: Any) -> dict:
    role_values = _role_schema_values(role_loader)
    role_summary = _role_schema_summary(role_loader)
    return {
        "name": "subagent_batch",
        "description": (
            "Run 1-5 independent SubAgent tasks concurrently. For multiple team "
            "members or roles, make ONE subagent_batch call with multiple task "
            "objects in tasks; set each task.role. Do not call this tool once per "
            "role when the work is independent."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": SUBAGENT_BATCH_LIMIT,
                    "description": (
                        "Sub-tasks to run in parallel. Put all independent role "
                        "assignments here in one call."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Short sub-task title, preferably including the assigned member name.",
                            },
                            "description": {
                                "type": "string",
                                "description": "Concrete instructions and context for this sub-task.",
                            },
                            "role": {
                                "type": "string",
                                "enum": role_values,
                                "description": (
                                    "Configured role id or display name for this task. "
                                    "Choose from the loaded role roster according to "
                                    f"the task type. Loaded roles: {role_summary}"
                                ),
                            },
                        },
                        "required": ["title", "description", "role"],
                    },
                },
                "role": {
                    "type": "string",
                    "enum": role_values,
                    "description": (
                        "Optional legacy default role for same-role batches only. "
                        "For multi-member work, leave this empty and set tasks[i].role."
                    ),
                },
            },
            "required": ["tasks"],
        },
    }


def _resolve_role_prompt(
    task_desc: dict, default_role: str | None, role_loader: Any,
) -> tuple[str | None, set[str] | None, str, str | None, str, str, str]:
    """Resolve role system_prompt and tools_override for a single sub-task.

    Priority: task-level role > batch-level default_role > None.

    Returns (role_system_prompt, tools_override_set_or_None).
    """
    role_name = task_desc.get("role") or _infer_role_name(task_desc, role_loader) or default_role
    if role_name is None:
        return None, None, "", None, "沈衡", "◈", "协调任务"
    role_obj = _resolve_role(role_name, role_loader)
    if role_obj is None:
        return None, None, "", role_name, str(role_name), "◈", "处理任务"
    return (
        role_obj.system_prompt,
        role_obj.tools_override,
        build_role_presence(role_obj),
        role_obj.name,
        role_obj.display_name,
        role_obj.icon,
        role_obj.status_text or "处理任务",
    )


def create_subagent_tools(
    session_manager: Any,
    agent: Any,
    role_loader: Any,
    base_tool_schemas: list[dict],
    max_turns: int = 70,
    event_bus: Any | None = None,
    memory_manager: Any | None = None,
) -> list:
    """Create SubAgent tool functions as closures.

    Returns a list of async functions ready to be registered into a
    ToolRegistry.
    """

    async def subagent_batch(
        tasks: list[dict[str, str]],
        role: str | None = None,
    ) -> str:
        """Create multiple SubAgents to execute sub-tasks in parallel.

        Use this when you need to split work into independent sub-tasks that
        can run concurrently. To run roles in parallel, put every independent
        role task in this ONE call. Do not call subagent_batch once per role
        unless the later role truly depends on earlier results.

        You can specify 1 to {max_limit} sub-tasks. A single sub-task is
        useful when you need context isolation from the current conversation.

        Args:
            tasks: List of sub-task descriptions. Each item MUST be an object
                with 'title', optional 'description', and optional 'role'.
                role must be a configured role id or display name, not a
                free-form prompt. Valid examples:
                [
                  {{"title": "调研竞品", "description": "...", "role": "researcher"}},
                  {{"title": "架构判断", "description": "...", "role": "executor"}},
                  {{"title": "整理汇报", "description": "...", "role": "reporter"}}
                ]
            role: Optional default role id/display name for tasks without a
                task-level role. Do NOT put role instructions here.
        """.format(max_limit=SUBAGENT_BATCH_LIMIT)

        if not tasks:
            return "错误：tasks 列表不能为空，请至少提供一个子任务。"

        normalized_tasks = []
        for i, item in enumerate(tasks, 1):
            if isinstance(item, str):
                normalized_tasks.append({"title": item[:80] or f"子任务 {i}", "description": item})
            elif isinstance(item, dict):
                normalized_tasks.append(item)
            else:
                return "错误：tasks 中的每一项都必须是对象，例如 {'title': '...', 'description': '...', 'role': 'research'}。"
        tasks = normalized_tasks

        if len(tasks) > SUBAGENT_BATCH_LIMIT:
            return (
                f"错误：单次 subagent_batch 调用最多支持 {SUBAGENT_BATCH_LIMIT} 个子任务。"
                f"你传了 {len(tasks)} 个，请分批调用。"
            )

        if role is not None and _resolve_role(role, role_loader) is None:
            all_tasks_have_roles = all(
                item.get("role") or _infer_role_name(item, role_loader)
                for item in tasks
            )
            if all_tasks_have_roles:
                role = None
            else:
                return (
                    "错误：role 必须是已配置的角色 id 或显示名，不能填写一段角色提示词。\n"
                    f"可用角色：{_available_roles(role_loader)}\n"
                    "请把角色分别写在 tasks[i].role 中，例如 role='research' 或 role='林澈'。"
                )

        async def run_one(task_desc: dict) -> str:
            title = task_desc.get("title", "")
            description = task_desc.get("description", "")
            if not title:
                return "错误：子任务缺少 title 字段。"

            role_prompt, tools_override, role_presence, resolved_role, display_name, icon, status_text = _resolve_role_prompt(
                task_desc, role, role_loader,
            )

            if task_desc.get("role") and resolved_role == task_desc.get("role") and role_prompt is None:
                return (
                    f"错误：未知角色 '{task_desc.get('role')}'。"
                    f"可用角色：{_available_roles(role_loader)}"
                )

            # Build system prompt
            role_memory = ""
            if memory_manager is not None and resolved_role:
                role_memory = memory_manager.assemble_role_memory(resolved_role)
            system_prompt = _build_subagent_prompt(
                title, description, role_prompt, role_presence, role_memory,
            )

            # Filter tools
            if tools_override is not None:
                allowed = set(tools_override) - SUBAGENT_BLOCKED_TOOLS
                sub_tools = [
                    t for t in base_tool_schemas
                    if t["function"]["name"] in allowed
                ]
            else:
                sub_tools = _filter_tools(base_tool_schemas)

            # Create session
            thread_id = session_manager.create_session(
                name=f"sub-{title[:30]}",
                session_type="managed",
                owner="scheduler",
            )
            thread_config = {
                "configurable": {"thread_id": thread_id},
                "recursion_limit": max_turns,
            }

            from src.core.background_executor import ManagedSession

            session = ManagedSession(
                thread_id=thread_id,
                agent=agent,
                config=thread_config,
                system_prompt=system_prompt,
                tools=sub_tools,
            )

            task_prompt = f"Task: {title}\n{description or '(no description)'}"
            try:
                if event_bus is not None:
                    await event_bus.emit(EventBus.ROLE_STARTED, {
                        "role": resolved_role or "default",
                        "display_name": display_name,
                        "icon": icon,
                        "title": title,
                        "status_text": status_text,
                        "thread_id": thread_id,
                    }, caller="subagent_batch", agent_id=resolved_role or "default")
                result = await asyncio.wait_for(
                    _run_with_semaphore(session.run(task_prompt)),
                    timeout=300,
                )
                if memory_manager is not None and resolved_role:
                    memory_manager.append_role_log(
                        role=resolved_role,
                        task_id=thread_id,
                        title=title,
                        result="done",
                        tools=getattr(session, "tools_used", []),
                        result_summary=result[:200] if result else None,
                    )
                if event_bus is not None:
                    await event_bus.emit(EventBus.ROLE_DONE, {
                        "role": resolved_role or "default",
                        "display_name": display_name,
                        "icon": icon,
                        "title": title,
                        "thread_id": thread_id,
                    }, caller="subagent_batch", agent_id=resolved_role or "default")
            except asyncio.TimeoutError:
                result = (
                    f"[SubAgent 超时] 子任务 '{title}' 执行超过 5 分钟未完成。"
                    "请判断：是否需要重新调用 subagent_batch 重试，或调整任务描述使其更聚焦。"
                )
                if event_bus is not None:
                    await event_bus.emit(EventBus.ROLE_FAILED, {
                        "role": resolved_role or "default",
                        "display_name": display_name,
                        "icon": icon,
                        "title": title,
                        "thread_id": thread_id,
                        "error": "timeout",
                    }, caller="subagent_batch", agent_id=resolved_role or "default")
                if memory_manager is not None and resolved_role:
                    memory_manager.append_role_log(
                        role=resolved_role,
                        task_id=thread_id,
                        title=title,
                        result="failed",
                        error="timeout",
                    )
            except Exception as e:
                result = f"[SubAgent 异常] 子任务 '{title}' 执行出错：{e}"
                if event_bus is not None:
                    await event_bus.emit(EventBus.ROLE_FAILED, {
                        "role": resolved_role or "default",
                        "display_name": display_name,
                        "icon": icon,
                        "title": title,
                        "thread_id": thread_id,
                        "error": str(e),
                    }, caller="subagent_batch", agent_id=resolved_role or "default")
                if memory_manager is not None and resolved_role:
                    memory_manager.append_role_log(
                        role=resolved_role,
                        task_id=thread_id,
                        title=title,
                        result="failed",
                        error=str(e),
                    )

            return result

        results = await asyncio.gather(
            *(run_one(t) for t in tasks),
            return_exceptions=True,
        )

        # Format output
        parts = ["## SubAgent 批量执行结果\n"]
        for i, (task_desc, result) in enumerate(zip(tasks, results), 1):
            title = task_desc.get("title", f"任务 {i}")
            if isinstance(result, Exception):
                parts.append(f"### {i}. {title}\n[异常] {result}\n")
            else:
                parts.append(f"### {i}. {title}\n{result}\n")
        return "\n".join(parts)

    subagent_batch.__tool_schema_factory__ = lambda: _build_subagent_batch_schema(role_loader)
    return [subagent_batch]

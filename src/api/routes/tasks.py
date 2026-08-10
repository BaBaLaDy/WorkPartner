"""Task CRUD routes."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from src.api.schemas import TaskCreateRequest, TaskUpdateRequest
from src.core.engine import WorkPartnerEngine
from src.hub.event_bus import EventBus

router = APIRouter(prefix="/tasks", tags=["tasks"])


def get_engine() -> WorkPartnerEngine:
    """Retrieve the globally stored engine instance."""
    from src.api.server import get_app_state
    return get_app_state().engine


@router.get("")
def list_tasks(status: str | None = None):
    """List all tasks, optionally filtered by status."""
    engine = get_engine()
    tasks = engine.todo_service.list(status=status)
    return {"tasks": tasks}


@router.post("")
async def create_task(body: TaskCreateRequest):
    """Create a new task."""
    engine = get_engine()
    task = engine.todo_service.add(
        title=body.title,
        description=body.description,
        priority=body.priority,
        role=body.role,
    )
    # Only wakeup executor when auto_run is True (default)
    if body.auto_run:
        engine.wakeup_executor(reason="task.created")
    await engine.event_bus.emit(
        EventBus.TASK_CREATED,
        {
            "task_id": task["id"],
            "title": task["title"],
            "status": task.get("status", "pending"),
            "role": task.get("role"),
            "priority": task.get("priority"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        caller="api",
        agent_id="user",
    )
    return task


@router.get("/{task_id}")
def get_task(task_id: str):
    """Get a single task by ID."""
    engine = get_engine()
    task = engine.todo_service.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}/session")
def get_task_session(task_id: str):
    """Get the LangGraph session conversation for a task.

    Returns the full conversation history (thinking, tools, responses)
    from the managed session that executed this task.
    """
    engine = get_engine()
    task = engine.todo_service.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    thread_id = task.get("session_thread_id")
    if not thread_id:
        return {"thread_id": None, "messages": [], "title": task["title"],
                "status": task["status"]}

    # Load messages from LangGraph checkpointer
    try:
        from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

        if engine.agent is None:
            return {"thread_id": thread_id, "messages": [], "title": task["title"],
                    "status": task["status"]}

        snapshot = engine.agent.get_state(
            {"configurable": {"thread_id": thread_id}}
        )
        if snapshot is None or not snapshot.values:
            return {"thread_id": thread_id, "messages": [], "title": task["title"],
                    "status": task["status"]}

        raw_messages = snapshot.values.get("messages", [])
        formatted = _format_messages(raw_messages)
        return {
            "thread_id": thread_id,
            "messages": formatted,
            "title": task["title"],
            "status": task["status"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load session: {e}")


def _format_messages(messages: list) -> list[dict]:
    """Format LangGraph messages for frontend, handling both live objects
    and deserialized dicts (from SQLite checkpointer)."""
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

    formatted = []
    for msg in messages:
        # --- Deserialized dict (common for done tasks loaded from SQLite) ---
        if isinstance(msg, dict):
            msg_type = msg.get("type", "")
            if msg_type == "human" or msg.get("role") == "user":
                formatted.append({"role": "user", "content": _to_str(msg.get("content"))})
            elif msg_type == "ai":
                content = msg.get("content")
                if content:
                    formatted.append({"role": "assistant", "content": _to_str(content)})
                tool_calls = msg.get("tool_calls") or msg.get("additional_kwargs", {}).get("tool_calls")
                if tool_calls:
                    first = tool_calls[0] if isinstance(tool_calls, list) else tool_calls
                    if isinstance(first, dict):
                        formatted.append({
                            "role": "tool_call",
                            "name": first.get("name", first.get("function", {}).get("name", "")),
                            "args": _parse_args(first.get("args", first.get("function", {}).get("arguments", "{}"))),
                        })
            elif msg_type == "tool" or msg.get("role") == "tool":
                content = msg.get("content", "")
                formatted.append({
                    "role": "tool_result",
                    "content": _to_str(content),
                    "tool_call_id": msg.get("tool_call_id", msg.get("id", "")),
                })
            continue

        # --- Live LangChain message objects ---
        if isinstance(msg, HumanMessage):
            formatted.append({"role": "user", "content": _to_str(msg.content)})
        elif isinstance(msg, AIMessage):
            if msg.content:
                formatted.append({"role": "assistant", "content": _to_str(msg.content)})
            if msg.tool_calls:
                tc = msg.tool_calls[0]
                formatted.append({"role": "tool_call", "name": tc.get("name", ""),
                                  "args": tc.get("args", {})})
        elif isinstance(msg, ToolMessage):
            content = _to_str(msg.content)
            if len(content) > 1000:
                content = content[:997] + "..."
            formatted.append({"role": "tool_result", "content": content,
                              "tool_call_id": msg.tool_call_id})
    return formatted


def _to_str(value) -> str:
    """Safely convert any message content to string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _parse_args(value) -> dict:
    """Safely parse tool-call args that may be a dict, JSON string, or None."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


@router.put("/{task_id}")
def update_task(task_id: str, body: TaskUpdateRequest):
    """Update a task."""
    engine = get_engine()
    update_fields = body.model_dump(exclude_unset=True)
    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    # If cancelling, also cancel the running executor task
    if update_fields.get("status") == "cancelled":
        engine.executor.cancel_task(task_id)

    result = engine.todo_service.update(task_id, **update_fields)
    if result is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


@router.delete("/{task_id}")
def delete_task(task_id: str):
    """Delete a task."""
    engine = get_engine()
    success = engine.todo_service.delete(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True}

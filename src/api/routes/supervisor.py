"""Supervisor routes for the team workbench."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/supervisor", tags=["supervisor"])


class SupervisorChatRequest(BaseModel):
    message: str
    thread_id: str | None = None


def get_engine():
    from src.api.server import get_app_state
    return get_app_state().engine


@router.get("/status")
def supervisor_status():
    """Return the event-driven supervisor snapshot for the frontend."""
    engine = get_engine()
    return engine.supervisor.status()


@router.post("/daily-report")
def supervisor_daily_report():
    """Generate a deterministic daily report from current task data."""
    engine = get_engine()
    report = engine.supervisor.daily_report()
    engine.memory.append_supervisor_log(
        event="daily_report",
        title="生成今日简报",
        detail="用户手动触发",
    )
    return {
        "report": report,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/memory-maintenance")
async def supervisor_memory_maintenance():
    """Run supervisor memory maintenance now."""
    engine = get_engine()
    return await engine.supervisor.memory_maintenance()


@router.post("/retry/{task_id}")
def supervisor_retry_task(task_id: str):
    """Ask the supervisor to put a task back into the pending queue."""
    engine = get_engine()
    return engine.supervisor.retry_task(task_id, reason="manual")


@router.post("/chat")
async def supervisor_chat(body: SupervisorChatRequest):
    """Send a message to the supervisor and receive a streaming SSE response."""
    engine = get_engine()
    session = engine.create_supervisor_session()
    system_prompt = engine.build_supervisor_system_prompt(body.message)
    # Use caller-supplied thread_id (session-based chat) or fall back to supervisor's fixed thread
    thread_id = body.thread_id or engine.supervisor.thread_id

    async def event_generator():
        async for event in session.stream_events(
            user_message=body.message,
            system_prompt=system_prompt,
            thread_id=thread_id,
        ):
            evt_type = event.get("event", "")
            data = event.get("data", "")
            if evt_type == "text_delta" and data:
                yield f"data: {json.dumps({'type': 'text', 'content': data})}\n\n"
            elif evt_type == "thinking_delta" and data:
                yield f"data: {json.dumps({'type': 'thinking', 'content': data})}\n\n"
            elif evt_type == "tool_input" and data:
                yield f"data: {json.dumps({'type': 'tool_start', 'data': data})}\n\n"
            elif evt_type == "tool_output" and data:
                yield f"data: {json.dumps({'type': 'tool_end', 'data': data})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/history")
def supervisor_chat_history():
    """Return the supervisor's conversation history as a list of messages."""
    engine = get_engine()
    try:
        config = {"configurable": {"thread_id": engine.supervisor.thread_id}}
        state = engine.agent.get_state(config)
        if state is None or not state.values:
            return []
        messages = state.values.get("messages", [])
        result: list[dict[str, Any]] = []
        for msg in messages:
            if hasattr(msg, "type") and msg.type in ("human", "ai"):
                content = msg.content if isinstance(msg.content, str) else ""
                if content:
                    result.append({"role": "user" if msg.type == "human" else "assistant", "content": content})
        return result
    except Exception:
        return []

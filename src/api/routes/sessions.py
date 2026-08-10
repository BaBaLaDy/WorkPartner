"""Session CRUD routes — list, create, switch, rename, delete, get messages."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.core.engine import WorkPartnerEngine

router = APIRouter(prefix="/sessions", tags=["sessions"])


def get_engine() -> WorkPartnerEngine:
    from src.api.server import get_app_state
    return get_app_state().engine


class SessionCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class SessionUpdateRequest(BaseModel):
    name: str | None = None
    action: str | None = None  # "switch", "delete"


@router.get("")
def list_sessions():
    """List all interactive sessions sorted by last_active."""
    engine = get_engine()
    sessions = engine.session_manager.list_sessions()
    active_id = engine.session_manager.active_id
    return {
        "sessions": sessions,
        "active_thread_id": active_id,
    }


@router.post("")
def create_session(body: SessionCreateRequest):
    """Create a new interactive session."""
    engine = get_engine()
    thread_id = engine.session_manager.create_session(
        name=body.name,
        session_type="interactive",
        owner="ui",
    )
    # Switch to the new session
    engine.session_manager.switch_session(thread_id)
    return {"thread_id": thread_id, "name": body.name}


@router.get("/{thread_id}/messages")
def get_session_messages(thread_id: str):
    """Get the conversation history for a specific session."""
    engine = get_engine()
    try:
        from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

        if engine.agent is None:
            return {"thread_id": thread_id, "messages": [], "title": ""}

        snapshot = engine.agent.get_state(
            {"configurable": {"thread_id": thread_id}}
        )
        if snapshot is None or not snapshot.values:
            return {"thread_id": thread_id, "messages": [], "title": ""}

        from src.api.routes.tasks import _format_messages

        raw_messages = snapshot.values.get("messages", [])
        formatted = _format_messages(raw_messages)
        return {
            "thread_id": thread_id,
            "messages": formatted,
            "title": "",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load messages: {e}")


@router.patch("/{thread_id}")
def update_session(thread_id: str, body: SessionUpdateRequest):
    """Switch active session or rename it."""
    engine = get_engine()

    if body.action == "delete":
        engine.session_manager.delete_session(thread_id)
        return {"ok": True}

    if body.action == "switch":
        engine.session_manager.switch_session(thread_id)
        return {"ok": True, "thread_id": thread_id}

    if body.name is not None:
        engine.session_manager.rename_session(thread_id, body.name)
        return {"ok": True, "name": body.name}

    raise HTTPException(status_code=400, detail="Provide 'name' or 'action'")

"""Executor control routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from src.hub.event_bus import EventBus

router = APIRouter(prefix="/executor", tags=["executor"])


def get_engine():
    from src.api.server import get_app_state
    return get_app_state().engine


@router.get("/status")
def executor_status():
    """Return background executor status."""
    engine = get_engine()
    return engine.executor_status()


@router.post("/wakeup")
async def wakeup_executor():
    """Ask the background executor to check pending tasks now."""
    engine = get_engine()
    status = engine.wakeup_executor(reason="api")
    await engine.event_bus.emit(
        EventBus.EXECUTOR_WAKEUP,
        {
            "reason": "api",
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        caller="api",
        agent_id="executor",
    )
    return {"ok": True, "status": status}


@router.put("/poll-interval")
def set_poll_interval(poll_interval: int):
    """Update executor poll interval (1-60 minutes)."""
    engine = get_engine()
    if not (1 <= poll_interval <= 60):
        return {"ok": False, "error": "poll_interval must be between 1 and 60 minutes"}
    engine.executor._poll_interval = float(poll_interval * 60)
    return {"ok": True, "poll_interval": poll_interval}

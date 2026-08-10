"""Server status endpoint."""

from fastapi import APIRouter

from src.api.schemas import ServerStatus
from src.core.engine import WorkPartnerEngine

router = APIRouter(prefix="/status", tags=["status"])


def get_engine() -> WorkPartnerEngine:
    from src.api.server import get_app_state
    return get_app_state().engine


@router.get("")
def get_status():
    """Get server health and service status."""
    engine = get_engine()
    from src.api.server import get_app_state
    return {
        "running": engine._running,
        "pending_tasks": engine.todo_service.pending_count,
        "active_schedules": engine.schedule_service.enabled_count,
        "websocket_connections": len(get_app_state().ws_manager.active_connections),
    }

"""Pin routes — list, mark read, archive."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from src.api.schemas import PinListResponse, PinResponse
from src.core.engine import WorkPartnerEngine

router = APIRouter(prefix="/pins", tags=["pins"])


def get_engine() -> WorkPartnerEngine:
    from src.api.server import get_app_state
    return get_app_state().engine


@router.get("")
def list_pins() -> PinListResponse:
    """List all pins with pin metadata, plus unread count."""
    engine = get_engine()
    sessions = engine.session_manager.list_sessions()
    pins = []
    for s in sessions:
        pin_data = s.get("pin")
        if pin_data and pin_data.get("summary"):
            pins.append(PinResponse(
                thread_id=s["thread_id"],
                title=s["name"],
                summary=pin_data["summary"],
                status=pin_data.get("status", "done"),
                created_at=pin_data.get("created_at", ""),
                read=pin_data.get("read", False),
                task_id=pin_data.get("task_id", ""),
            ))
    unread_count = sum(1 for p in pins if not p.read)
    return PinListResponse(pins=pins, unread_count=unread_count)


@router.post("/{thread_id}/read")
def mark_pin_read(thread_id: str) -> PinResponse:
    """Mark a pin as read."""
    return _update_pin_read(thread_id, True)


@router.post("/{thread_id}/archive")
def archive_pin(thread_id: str) -> PinResponse:
    """Archive a pin (sets read=True)."""
    return _update_pin_read(thread_id, True)


def _update_pin_read(thread_id: str, read: bool) -> PinResponse:
    engine = get_engine()
    sm = engine.session_manager
    meta = sm._data["sessions"].get(thread_id)
    if meta is None or not meta.get("pin"):
        raise HTTPException(status_code=404, detail="Pin not found")

    meta["pin"]["read"] = read
    sm._save_index()

    return PinResponse(
        thread_id=thread_id,
        title=meta.get("name", thread_id),
        summary=meta["pin"]["summary"],
        status=meta["pin"].get("status", "done"),
        created_at=meta["pin"].get("created_at", ""),
        read=read,
        task_id=meta["pin"].get("task_id", ""),
    )

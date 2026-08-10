"""Schedule CRUD routes."""

from fastapi import APIRouter, HTTPException

from src.api.schemas import ScheduleCreateRequest
from src.core.engine import WorkPartnerEngine

router = APIRouter(prefix="/schedules", tags=["schedules"])


def get_engine() -> WorkPartnerEngine:
    from src.api.server import get_app_state
    return get_app_state().engine


@router.get("")
def list_schedules():
    """List all schedules."""
    engine = get_engine()
    schedules = engine.schedule_service.list()
    return {"schedules": [s.to_dict() if hasattr(s, "to_dict") else _serialize(s) for s in schedules]}


@router.post("")
def create_schedule(body: ScheduleCreateRequest):
    """Create a new schedule."""
    engine = get_engine()
    schedule = engine.schedule_service.add(
        name=body.title,
        schedule_type=body.type,
        trigger_at=body.trigger_at,
        cron_expression=body.cron_expression,
        task_description=body.task_description,
    )
    # Register with APScheduler
    engine.scheduler.add_schedule(schedule)
    return _serialize(schedule)


@router.patch("/{schedule_id}/pause")
def pause_schedule(schedule_id: str):
    """Pause a schedule."""
    engine = get_engine()
    result = engine.scheduler.pause_schedule(schedule_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return _serialize(result)


@router.patch("/{schedule_id}/resume")
def resume_schedule(schedule_id: str):
    """Resume a paused schedule."""
    engine = get_engine()
    result = engine.scheduler.resume_schedule(schedule_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return _serialize(result)


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: str):
    """Delete a schedule."""
    engine = get_engine()
    success = engine.scheduler.delete_schedule(schedule_id)
    if not success:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"ok": True}


def _serialize(schedule) -> dict:
    """Serialize a ScheduledTask to dict."""
    if hasattr(schedule, "to_dict"):
        return schedule.to_dict()
    if isinstance(schedule, dict):
        return schedule
    # Fallback: convert from object attributes
    return {
        "id": getattr(schedule, "id", ""),
        "name": getattr(schedule, "name", ""),
        "schedule_type": getattr(schedule, "schedule_type", ""),
        "cron_expression": getattr(schedule, "cron_expression", None),
        "trigger_at": getattr(schedule, "trigger_at", None),
        "enabled": getattr(schedule, "enabled", True),
        "task_title": getattr(schedule, "task_title", ""),
        "task_description": getattr(schedule, "task_description", ""),
        "task_priority": getattr(schedule, "task_priority", "medium"),
        "created_at": getattr(schedule, "created_at", None),
        "last_triggered_at": getattr(schedule, "last_triggered_at", None),
    }

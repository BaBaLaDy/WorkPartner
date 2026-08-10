"""Office state routes — high-level semantic office status."""

from __future__ import annotations

import time
from threading import Lock
from typing import Any

from fastapi import APIRouter

from src.hub.event_bus import EventBus

router = APIRouter(prefix="/office", tags=["office"])


def get_engine():
    from src.api.server import get_app_state
    return get_app_state().engine


# -- Response cache (TTL 5s, event-invalidated) --

class _OfficeStateCache:
    def __init__(self, ttl: int = 5):
        self._ttl = ttl
        self._value: dict[str, Any] | None = None
        self._expires_at: float = 0
        self._lock = Lock()

    def get(self) -> dict[str, Any] | None:
        with self._lock:
            if self._value is not None and time.time() < self._expires_at:
                return self._value
            self._value = None
            return None

    def set(self, value: dict[str, Any]) -> None:
        with self._lock:
            self._value = value
            self._expires_at = time.time() + self._ttl

    def invalidate(self) -> None:
        with self._lock:
            self._value = None


_cache = _OfficeStateCache()


def _subscribe_cache_invalidation(engine) -> None:
    """Subscribe to relevant events to invalidate the office state cache."""

    async def _on_event(event) -> None:
        _cache.invalidate()

    for event_name in [
        EventBus.TASK_DONE,
        EventBus.TASK_FAILED,
        EventBus.TASK_CREATED,
        EventBus.TASK_STARTED,
        EventBus.TASK_CANCELLED,
        EventBus.ROLE_STARTED,
        EventBus.ROLE_DONE,
        EventBus.ROLE_FAILED,
    ]:
        engine.event_bus.subscribe(event_name, _on_event)


# -- State calculation --

def _compute_office_mood(tasks: list[dict], supervisor_status: dict | None) -> str:
    """Derive overall office mood from task and supervisor state."""
    in_progress = [t for t in tasks if t.get("status") == "in_progress"]
    failed = [t for t in tasks if t.get("status") == "failed"]

    if failed:
        return "attention_needed"
    if in_progress:
        return "busy"
    return "idle"


def _compute_active_members(engine) -> list[dict]:
    """Get currently active (non-idle) role members."""
    status = engine.supervisor.status()
    team = status.get("team", [])
    active = []
    for member in team:
        state = member.get("state", "idle")
        if state != "idle":
            active.append({
                "name": member.get("display_name", member.get("name", "")),
                "status": state,
                "task": member.get("current_task_title"),
            })
    return active


def _compute_all_members(engine) -> list[dict]:
    """Get all role members with their current state."""
    status = engine.supervisor.status()
    team = status.get("team", [])
    members = []
    for member in team:
        state = member.get("state", "idle")
        members.append({
            "name": member.get("display_name", member.get("name", "")),
            "status": state,
            "task": member.get("current_task_title"),
        })
    return members


def _compute_recent_handovers(engine, limit: int = 5) -> list[str]:
    """Get recent handover narratives from the dispatch log."""
    try:
        from src.narrative import EventClassifier, Narrator
    except ImportError:
        return []

    classifier = EventClassifier()
    narrator = Narrator()

    # Read recent role dispatch entries
    try:
        dispatches = engine.memory.read_role_dispatch(limit=limit)
    except AttributeError:
        return []

    handovers = []
    for disp in dispatches:
        role_name = disp.get("role", "")
        role = engine.role_loader.get(role_name) if engine.role_loader else None
        summary = classifier.classify(
            type("_AgentEvent", (), {
                "type": "role.done",
                "payload": {"role": role_name, "title": disp.get("task_type", ""), "quality": "pass"},
            })(),
            role_loader=engine.role_loader,
        )
        handovers.append(narrator.narrate(summary, role=role))

    return handovers


def _compute_pending_attention(tasks: list[dict]) -> list[dict]:
    """Find tasks that need user intervention (failed with retry < 2)."""
    pending = []
    for task in tasks:
        status = task.get("status", "")
        if status == "in_progress" or status == "failed":
            retry_count = task.get("retry_count", 0)
            if retry_count < 2:
                pending.append({
                    "task_id": task.get("id", ""),
                    "reason": f"任务{'未通过质量检查' if status == 'failed' else '执行中'}",
                    "retry_count": retry_count,
                })
    return pending


def _compute_suggested_next_action(engine, tasks: list[dict]) -> str | None:
    """Suggest a next action if an idle role has pending tasks."""
    status = engine.supervisor.status()
    team = status.get("team", [])

    idle_member = None
    for member in team:
        if member.get("state") == "idle":
            idle_member = member
            break

    if not idle_member:
        return None

    pending = [t for t in tasks if t.get("status") == "pending"]
    if not pending:
        return None

    next_task = pending[0]
    display_name = idle_member.get("display_name", idle_member.get("name", ""))
    return f"{display_name}可以开始处理{next_task.get('title', '')}任务"


@router.get("/state")
def get_office_state():
    """Return high-level semantic office state.

    Response is cached for 5 seconds and invalidated on relevant events.
    """
    engine = get_engine()

    # Check cache
    cached = _cache.get()
    if cached is not None:
        return cached

    tasks = engine.todo_service.list()
    supervisor = engine.supervisor.status()

    state = {
        "office_mood": _compute_office_mood(tasks, supervisor),
        "active_members": _compute_all_members(engine),
        "recent_handovers": _compute_recent_handovers(engine),
        "pending_attention": _compute_pending_attention(tasks),
        "suggested_next_action": _compute_suggested_next_action(engine, tasks),
    }

    _cache.set(state)
    return state

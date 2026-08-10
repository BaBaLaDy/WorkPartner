"""TaskScheduler — cron-based scheduling that feeds into the Todo queue."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ScheduledTask data model
# ---------------------------------------------------------------------------

@dataclass
class ScheduledTask:
    """A schedule template that generates todo items when triggered.

    Two types:
      - "once": fires at trigger_at, then auto-disables
      - "recurring": fires on each cron match, repeats indefinitely
    """

    id: str
    name: str
    schedule_type: str  # "once" | "recurring"
    trigger_at: str | None = None  # ISO datetime for "once"
    cron_expression: str | None = None  # "0 9 * * *" for "recurring"
    task_title: str = ""
    task_description: str = ""
    task_priority: str = "medium"  # "high" | "medium" | "low"
    enabled: bool = True
    last_triggered: str | None = None
    created_at: str = ""
    # runtime counter (not persisted between restarts, but useful while running)
    execution_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "schedule_type": self.schedule_type,
            "trigger_at": self.trigger_at,
            "cron_expression": self.cron_expression,
            "task_title": self.task_title,
            "task_description": self.task_description,
            "task_priority": self.task_priority,
            "enabled": self.enabled,
            "last_triggered": self.last_triggered,
            "created_at": self.created_at,
            "execution_count": self.execution_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ScheduledTask":
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            schedule_type=d.get("schedule_type", "once"),
            trigger_at=d.get("trigger_at"),
            cron_expression=d.get("cron_expression"),
            task_title=d.get("task_title", ""),
            task_description=d.get("task_description", ""),
            task_priority=d.get("task_priority", "medium"),
            enabled=d.get("enabled", True),
            last_triggered=d.get("last_triggered"),
            created_at=d.get("created_at", ""),
            execution_count=d.get("execution_count", 0),
        )

    @property
    def next_trigger_text(self) -> str:
        """Human-readable next trigger time."""
        if not self.enabled:
            return "已暂停"
        if self.schedule_type == "once":
            return self.trigger_at or "未设置"
        return f"cron: {self.cron_expression}"


# ---------------------------------------------------------------------------
# ScheduledTaskManager — CRUD + JSON persistence
# ---------------------------------------------------------------------------

class ScheduledTaskManager:
    """Manages scheduled task templates persisted to scheduled_tasks.json."""

    def __init__(self, file_path: str = "scheduled_tasks.json"):
        self._path = Path(file_path)
        self._schedules: dict[str, ScheduledTask] = {}
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for item in data.get("schedules", []):
                    st = ScheduledTask.from_dict(item)
                    self._schedules[st.id] = st
            except (json.JSONDecodeError, ValueError):
                self._schedules = {}
        else:
            self._schedules = {}

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schedules": [st.to_dict() for st in self._schedules.values()]
        }
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---- CRUD ----

    def add(
        self,
        name: str,
        schedule_type: str,
        task_title: str = "",
        task_description: str = "",
        task_priority: str = "medium",
        trigger_at: str | None = None,
        cron_expression: str | None = None,
    ) -> ScheduledTask:
        st = ScheduledTask(
            id=uuid.uuid4().hex[:8],
            name=name.strip(),
            schedule_type=schedule_type,
            trigger_at=trigger_at,
            cron_expression=cron_expression,
            task_title=task_title.strip(),
            task_description=task_description.strip(),
            task_priority=task_priority,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._schedules[st.id] = st
        self._save()
        return st

    def get(self, schedule_id: str) -> ScheduledTask | None:
        return self._schedules.get(schedule_id)

    def list(self, enabled_only: bool = False) -> list[ScheduledTask]:
        result = list(self._schedules.values())
        if enabled_only:
            result = [s for s in result if s.enabled]
        # Sort by name for stable display
        result.sort(key=lambda s: s.name)
        return result

    def update(self, schedule_id: str, **kwargs) -> ScheduledTask | None:
        st = self._schedules.get(schedule_id)
        if st is None:
            return None
        mutable_fields = (
            "name",
            "task_title",
            "task_description",
            "task_priority",
            "trigger_at",
            "cron_expression",
            "enabled",
        )
        for k, v in kwargs.items():
            if k in mutable_fields and v is not None:
                setattr(st, k, v)
        self._save()
        return st

    def delete(self, schedule_id: str) -> bool:
        if schedule_id not in self._schedules:
            return False
        del self._schedules[schedule_id]
        self._save()
        return True

    def set_enabled(self, schedule_id: str, enabled: bool) -> ScheduledTask | None:
        st = self._schedules.get(schedule_id)
        if st is None:
            return None
        st.enabled = enabled
        self._save()
        return st

    def record_trigger(self, schedule_id: str) -> ScheduledTask | None:
        """Update last_triggered and increment execution_count after a trigger fires."""
        st = self._schedules.get(schedule_id)
        if st is None:
            return None
        st.last_triggered = datetime.now(timezone.utc).isoformat()
        st.execution_count += 1
        self._save()
        return st

    @property
    def count(self) -> int:
        return len(self._schedules)

    @property
    def enabled_count(self) -> int:
        return sum(1 for s in self._schedules.values() if s.enabled)

    @property
    def all_ids(self) -> list[str]:
        return list(self._schedules.keys())


# ---------------------------------------------------------------------------
# TaskScheduler — APScheduler wrapper
# ---------------------------------------------------------------------------

class TaskScheduler:
    """Wraps AsyncIOScheduler to trigger todo creation on schedule.

    Design: when a schedule fires, it calls TodoManager.add() to create a
    pending todo. The managed mode loop picks it up naturally — no separate
    execution path. This keeps one source of truth for all tasks.
    """

    def __init__(
        self,
        store: ScheduledTaskManager,
        todo: Any = None,  # TodoManager, injected after init to avoid circular import
        timezone_str: str = "Asia/Shanghai",
    ):
        self._store = store
        self._todo = todo
        self._timezone = timezone_str
        self._scheduler = BackgroundScheduler(timezone=timezone_str)
        self._job_ids: dict[str, str] = {}  # schedule_id → apscheduler job_id

    @property
    def scheduler(self) -> BackgroundScheduler:
        return self._scheduler

    def set_todo(self, todo):
        """Set the TodoManager reference (call after AgentSession init)."""
        self._todo = todo

    # ---- lifecycle ----

    def start(self):
        """Start the scheduler and register all enabled schedules."""
        self._load_all_schedules()
        self._scheduler.start()
        enabled = self._store.enabled_count
        total = self._store.count
        logger.info(
            "TaskScheduler started — %d/%d schedules active (timezone=%s)",
            enabled, total, self._timezone,
        )

    def shutdown(self, wait: bool = False):
        """Graceful shutdown."""
        self._scheduler.shutdown(wait=wait)
        logger.info("TaskScheduler shut down")

    # ---- schedule registration ----

    def _load_all_schedules(self):
        """Load all enabled schedules from the store and register APScheduler jobs."""
        for st in self._store.list():
            if st.schedule_type == "once" and st.trigger_at:
                # One-shot: check if past-due
                try:
                    trigger_dt = datetime.fromisoformat(st.trigger_at)
                    now = datetime.now(timezone.utc)
                    # Handle naive datetime (no timezone) — treat as local
                    if trigger_dt.tzinfo is None:
                        from datetime import timezone as _tz
                        trigger_dt = trigger_dt.replace(tzinfo=_tz.utc)
                    if trigger_dt <= now:
                        if st.enabled:
                            self._store.set_enabled(st.id, False)
                            logger.info(
                                "One-shot schedule '%s' (%s) is past-due — auto-disabled",
                                st.name, st.id,
                            )
                        continue
                except ValueError:
                    logger.warning("Invalid trigger_at for schedule '%s': %s", st.name, st.trigger_at)
                    continue
            if st.enabled:
                self._register_job(st)

    def _register_job(self, st: ScheduledTask):
        """Register a single schedule as an APScheduler job."""
        trigger = self._make_trigger(st)
        job_id = f"cron_{st.id}"
        self._scheduler.add_job(
            self._on_trigger,
            trigger=trigger,
            args=[st.id],
            id=job_id,
            replace_existing=True,
            misfire_grace_time=300,  # 5 min — fire if missed by up to 5 min
        )
        self._job_ids[st.id] = job_id

    def _unregister_job(self, schedule_id: str):
        """Remove an APScheduler job for a schedule."""
        job_id = self._job_ids.pop(schedule_id, None)
        if job_id:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                # Job may have already been removed (e.g., during pause)
                pass

    def _make_trigger(self, st: ScheduledTask):
        """Create the appropriate APScheduler trigger for a schedule."""
        if st.schedule_type == "once" and st.trigger_at:
            return DateTrigger(
                run_date=datetime.fromisoformat(st.trigger_at),
                timezone=self._timezone,
            )
        elif st.schedule_type == "recurring" and st.cron_expression:
            parts = st.cron_expression.strip().split()
            return CronTrigger(
                minute=parts[0] if len(parts) > 0 else "*",
                hour=parts[1] if len(parts) > 1 else "*",
                day=parts[2] if len(parts) > 2 else "*",
                month=parts[3] if len(parts) > 3 else "*",
                day_of_week=parts[4] if len(parts) > 4 else "*",
                timezone=self._timezone,
            )
        else:
            raise ValueError(
                f"Invalid schedule config for '{st.name}': type={st.schedule_type}"
            )

    # ---- trigger callback ----

    def _on_trigger(self, schedule_id: str):
        """Called by APScheduler when a schedule fires.

        Creates a todo item from the schedule template. For one-shot schedules,
        auto-disables after the first fire.
        """
        st = self._store.get(schedule_id)
        if st is None:
            logger.warning("Schedule '%s' not found on trigger — removing job", schedule_id)
            self._unregister_job(schedule_id)
            return

        if not st.enabled:
            logger.info("Schedule '%s' is disabled, skipping trigger", st.name)
            return

        logger.info("Trigger fired: '%s' (%s)", st.name, st.id)

        # Create the todo
        if self._todo:
            self._todo.add(
                title=st.task_title or st.name,
                description=st.task_description,
                priority=st.task_priority,
                parent_schedule_id=st.id,
                schedule_type=st.schedule_type,
                cron_expression=st.cron_expression,
            )

        # Update state
        self._store.record_trigger(schedule_id)

        # One-shot: disable after firing
        if st.schedule_type == "once":
            self._store.set_enabled(schedule_id, False)
            self._unregister_job(schedule_id)
            logger.info("One-shot schedule '%s' completed — auto-disabled", st.name)

    # ---- public API for tools / UI ----

    def add_schedule(self, st: ScheduledTask):
        """Register a newly created schedule with APScheduler if enabled."""
        if st.enabled:
            self._register_job(st)

    def update_schedule(self, schedule_id: str, **kwargs):
        """Update a schedule and reschedule if timing changed."""
        st = self._store.update(schedule_id, **kwargs)
        if st is None:
            return None
        # Reschedule: remove old job, re-add if still enabled
        self._unregister_job(schedule_id)
        if st.enabled:
            self._register_job(st)
        return st

    def delete_schedule(self, schedule_id: str) -> bool:
        """Delete a schedule from both APScheduler and persistence."""
        self._unregister_job(schedule_id)
        return self._store.delete(schedule_id)

    def pause_schedule(self, schedule_id: str):
        """Pause a schedule (disable + remove APScheduler job)."""
        st = self._store.set_enabled(schedule_id, False)
        if st:
            self._unregister_job(schedule_id)
        return st

    def resume_schedule(self, schedule_id: str):
        """Resume a paused schedule (enable + re-add APScheduler job)."""
        st = self._store.set_enabled(schedule_id, True)
        if st:
            self._register_job(st)
        return st

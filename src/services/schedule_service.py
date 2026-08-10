"""ScheduleService — singleton wrapper around ScheduledTaskManager with write locking."""

from __future__ import annotations

import threading

from src.tasks.scheduler import ScheduledTask, ScheduledTaskManager


class ScheduleService:
    """Thin service layer over ScheduledTaskManager.

    Provides:
    - Single in-memory source of truth per process
    - threading.Lock on all write operations
    - Passthrough read operations

    Design note: the APScheduler TaskScheduler is a separate concern (runtime
    scheduling engine). This service handles the CRUD/persistence layer only.
    """

    def __init__(self, file_path: str = "scheduled_tasks.json"):
        self._manager = ScheduledTaskManager(file_path)
        self._lock = threading.Lock()

    # -- CRUD --

    def add(self, name: str, schedule_type: str, task_title: str = "",
            task_description: str = "", task_priority: str = "medium",
            trigger_at: str | None = None,
            cron_expression: str | None = None) -> ScheduledTask:
        with self._lock:
            return self._manager.add(
                name, schedule_type, task_title, task_description,
                task_priority, trigger_at, cron_expression,
            )

    def get(self, schedule_id: str) -> ScheduledTask | None:
        return self._manager.get(schedule_id)

    def list(self, enabled_only: bool = False) -> list[ScheduledTask]:
        return self._manager.list(enabled_only)

    def update(self, schedule_id: str, **kwargs) -> ScheduledTask | None:
        with self._lock:
            return self._manager.update(schedule_id, **kwargs)

    def delete(self, schedule_id: str) -> bool:
        with self._lock:
            return self._manager.delete(schedule_id)

    def set_enabled(self, schedule_id: str, enabled: bool) -> ScheduledTask | None:
        with self._lock:
            return self._manager.set_enabled(schedule_id, enabled)

    def record_trigger(self, schedule_id: str) -> ScheduledTask | None:
        with self._lock:
            return self._manager.record_trigger(schedule_id)

    # -- Properties --

    @property
    def count(self) -> int:
        return self._manager.count

    @property
    def enabled_count(self) -> int:
        return self._manager.enabled_count

    @property
    def all_ids(self) -> list[str]:
        return self._manager.all_ids

    # -- Backing manager access (for TaskScheduler) --

    @property
    def manager(self) -> ScheduledTaskManager:
        return self._manager

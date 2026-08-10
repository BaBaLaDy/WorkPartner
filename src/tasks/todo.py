"""TodoManager — CRUD operations on tasks.json."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

TaskStatus = Literal["pending", "in_progress", "done", "cancelled", "failed"]
TaskPriority = Literal["high", "medium", "low"]


class TodoManager:
    """Manages a task list persisted to a JSON file."""

    def __init__(self, file_path: str = "tasks.json"):
        self._path = Path(file_path)
        self._tasks: list[dict] = []
        self._load()

    # ---- file I/O ----

    def _load(self):
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._tasks = data.get("tasks", [])
            except (json.JSONDecodeError, ValueError):
                self._tasks = []
        else:
            self._tasks = []

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"tasks": self._tasks}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---- CRUD ----

    def add(self, title: str, description: str = "", priority: TaskPriority = "medium",
            session_id: str = "",
            parent_schedule_id: str | None = None,
            schedule_type: str | None = None,
            cron_expression: str | None = None,
            role: str | None = None) -> dict:
        task = {
            "id": uuid.uuid4().hex[:8],
            "title": title.strip(),
            "description": description.strip(),
            "status": "pending",
            "priority": priority,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "created_in_session": session_id or None,
            "completed_in_session": None,
            "session_thread_id": None,
            # Schedule linkage (null when created manually)
            "parent_schedule_id": parent_schedule_id,
            "schedule_type": schedule_type,
            "cron_expression": cron_expression,
            "role": role,
        }
        self._tasks.append(task)
        self._save()
        return task

    def update(self, task_id: str, session_id: str = "", **kwargs) -> dict | None:
        task = self.get(task_id)
        if task is None:
            return None
        for k, v in kwargs.items():
            if k in (
                "title", "description", "status", "priority", "session_thread_id",
                "supervisor_quality", "supervisor_note", "supervisor_retry_count",
            ):
                task[k] = v
        if kwargs.get("status") == "done" and task["completed_at"] is None:
            task["completed_at"] = datetime.now(timezone.utc).isoformat()
            if session_id:
                task["completed_in_session"] = session_id
        if kwargs.get("status") == "pending":
            task["completed_at"] = None
        self._save()
        return task

    def delete(self, task_id: str) -> bool:
        task = self.get(task_id)
        if task is None:
            return False
        self._tasks.remove(task)
        self._save()
        return True

    def get(self, task_id: str) -> dict | None:
        for t in self._tasks:
            if t["id"] == task_id:
                return t
        return None

    def list(self, status: TaskStatus | None = None) -> list[dict]:
        if status is None:
            return list(self._tasks)
        return [t for t in self._tasks if t["status"] == status]

    # ---- priority ordering ----

    def get_next_pending(self) -> dict | None:
        order = {"high": 0, "medium": 1, "low": 2}
        # Re-load from file to pick up changes from other processes
        self._load()
        pending = [t for t in self._tasks if t["status"] == "pending"]
        if not pending:
            return None
        pending.sort(key=lambda t: (order.get(t["priority"], 1), t["created_at"]))
        return pending[0]

    def mark_in_progress(self, task_id: str) -> dict | None:
        return self.update(task_id, status="in_progress")

    def mark_done(self, task_id: str, session_id: str = "") -> dict | None:
        return self.update(task_id, status="done", session_id=session_id)

    def mark_cancelled(self, task_id: str) -> dict | None:
        return self.update(task_id, status="cancelled")

    def mark_failed(self, task_id: str, session_id: str = "") -> dict | None:
        return self.update(task_id, status="failed", session_id=session_id)

    @property
    def pending_count(self) -> int:
        return sum(1 for t in self._tasks if t["status"] == "pending")

    @property
    def done_count(self) -> int:
        return sum(1 for t in self._tasks if t["status"] == "done")

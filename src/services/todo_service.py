"""TodoService — singleton wrapper around TodoManager with write locking."""

import threading

from src.tasks.todo import TodoManager


class TodoService:
    """Thin service layer over TodoManager.

    Provides:
    - Single in-memory source of truth per process
    - threading.Lock on all write operations (add/update/delete/save)
    - Passthrough read operations (no lock needed — GIL protects list access)

    All CRUD delegates to the inner TodoManager's in-memory state.
    File I/O occurs only on _save(), protected by the write lock.
    """

    def __init__(self, file_path: str = "tasks.json"):
        self._manager = TodoManager(file_path)
        self._lock = threading.Lock()

    # -- CRUD (writes locked, reads unlocked) --

    def add(self, title: str, description: str = "", priority: str = "medium",
            session_id: str = "", **kwargs) -> dict:
        with self._lock:
            return self._manager.add(title, description, priority, session_id, **kwargs)

    def update(self, task_id: str, session_id: str = "", **kwargs) -> dict | None:
        with self._lock:
            return self._manager.update(task_id, session_id, **kwargs)

    def delete(self, task_id: str) -> bool:
        with self._lock:
            return self._manager.delete(task_id)

    def get(self, task_id: str) -> dict | None:
        return self._manager.get(task_id)

    def list(self, status: str | None = None) -> list[dict]:
        return self._manager.list(status)

    # -- Workflow helpers --

    def get_next_pending(self) -> dict | None:
        return self._manager.get_next_pending()

    def mark_in_progress(self, task_id: str) -> dict | None:
        with self._lock:
            return self._manager.mark_in_progress(task_id)

    def mark_done(self, task_id: str, session_id: str = "") -> dict | None:
        with self._lock:
            return self._manager.mark_done(task_id, session_id)

    def mark_cancelled(self, task_id: str) -> dict | None:
        with self._lock:
            return self._manager.mark_cancelled(task_id)

    def mark_failed(self, task_id: str, session_id: str = "") -> dict | None:
        with self._lock:
            return self._manager.mark_failed(task_id, session_id)

    # -- Properties --

    @property
    def pending_count(self) -> int:
        return self._manager.pending_count

    @property
    def done_count(self) -> int:
        return self._manager.done_count

    # -- Backing manager access (for TaskScheduler that needs raw TodoManager) --

    @property
    def manager(self) -> TodoManager:
        return self._manager

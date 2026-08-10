"""TodoList tools — exposed to the agent so it can manage tasks via tool calls.

These are CLI- and UI-agnostic: they operate on a shared TodoService instance.
The service must be initialized via setup_todo_service() before any tool is called.
"""

_todo_service = None  # TodoService instance, set by setup_todo_service()


def setup_todo_service(service):
    """Inject the TodoService so tool functions use shared state."""
    global _todo_service
    _todo_service = service


def _get_service():
    if _todo_service is None:
        raise RuntimeError(
            "TodoService not initialized. Call setup_todo_service() "
            "during application startup before any tool is invoked."
        )
    return _todo_service


def todo_add(title: str, description: str = "", priority: str = "medium") -> str:
    """Add a task to the TodoList. Use this when the user asks you to remember,
    track, or do something later.

    Args:
        title: Short task title (required)
        description: Optional details about the task
        priority: 'high', 'medium', or 'low' (default: 'medium')
    """
    if not title or not title.strip():
        return "Error: title is required"
    if priority not in ("high", "medium", "low"):
        return "Error: priority must be 'high', 'medium', or 'low'"
    svc = _get_service()
    task = svc.add(title.strip(), description.strip(), priority)
    return (
        f"Task added: [{task['id']}] {task['title']} "
        f"(priority: {task['priority']}, status: {task['status']})"
    )


def todo_list(status: str = "pending") -> str:
    """List tasks in the TodoList.

    Args:
        status: Filter by status — 'pending' (default), 'in_progress', 'done',
                'cancelled', or 'all' for everything.
    """
    svc = _get_service()
    filter_status = None if status == "all" else status
    tasks = svc.list(filter_status)

    if not tasks:
        return f"No tasks found" + (f" with status '{status}'" if status != "all" else "")

    lines = [f"{len(tasks)} task(s):"]
    icon = {"pending": "[ ]", "in_progress": "[>]", "done": "[x]", "cancelled": "[-]"}
    for t in tasks:
        i = icon.get(t["status"], "[ ]")
        desc = f" — {t['description'][:60]}" if t.get("description") else ""
        lines.append(
            f"  {i} [{t['id']}] {t['title']}{desc} "
            f"({t['priority']}, {t['status']})"
        )
    return "\n".join(lines)


def todo_update(task_id: str, status: str = "", title: str = "") -> str:
    """Update a task's status or title. Use after completing a task to mark it done.

    Args:
        task_id: The task ID (from todo_list output)
        status: New status — 'done', 'cancelled', 'pending', 'in_progress' (optional)
        title: New title (optional, rarely used)
    """
    svc = _get_service()
    task = svc.get(task_id)
    if task is None:
        return f"Error: task '{task_id}' not found. Use todo_list to see all task IDs."

    kwargs = {}
    if status:
        if status not in ("pending", "in_progress", "done", "cancelled"):
            return "Error: status must be 'pending', 'in_progress', 'done', or 'cancelled'"
        kwargs["status"] = status
    if title:
        kwargs["title"] = title.strip()

    if not kwargs:
        return "Error: provide at least one field to update"

    updated = svc.update(task_id, **kwargs)
    if updated is None:
        return f"Error: failed to update task '{task_id}'"
    return (
        f"Task updated: [{updated['id']}] {updated['title']} "
        f"(status: {updated['status']})"
    )


def todo_delete(task_id: str) -> str:
    """Delete a task from the TodoList permanently.

    Args:
        task_id: The task ID to delete
    """
    svc = _get_service()
    task = svc.get(task_id)
    if task is None:
        return f"Error: task '{task_id}' not found. Use todo_list to see all task IDs."
    svc.delete(task_id)
    return f"Task deleted: [{task_id}] {task['title']}"

"""Cron schedule tools — agent-facing tools for managing scheduled tasks.

Pattern: module-level refs set by setup functions on startup.
Individual tool functions read/write via the shared ScheduleService + TaskScheduler.
"""

# Module-level references set by setup functions
_scheduler = None  # TaskScheduler instance (APScheduler runtime)
_schedule_service = None  # ScheduleService instance (CRUD/persistence)


def setup_cron_tools(scheduler):
    """Inject the TaskScheduler instance so tools can register/update APScheduler jobs."""
    global _scheduler
    _scheduler = scheduler


def setup_schedule_service(service):
    """Inject the ScheduleService so tools use shared state."""
    global _schedule_service
    _schedule_service = service


def _get_service():
    """Get the injected ScheduleService, raising if not initialized."""
    if _schedule_service is None:
        raise RuntimeError(
            "ScheduleService not initialized. Call setup_schedule_service() "
            "during application startup before any cron tool is invoked."
        )
    return _schedule_service


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# ---- tool functions ----


def cron_add(
    name: str,
    schedule_type: str,
    task_title: str = "",
    task_description: str = "",
    task_priority: str = "medium",
    trigger_at: str = "",
    cron_expression: str = "",
) -> str:
    """Create a scheduled task that will generate a todo at the specified time.

    Use this when the user wants something done at a specific future time,
    or on a recurring schedule (e.g., "remind me at 3pm", "every morning at 9").

    Args:
        name: Short name for this schedule (e.g., "每日早报", "会议提醒")
        schedule_type: 'once' (fires once then disables) or 'recurring' (repeats)
        task_title: Title for the todo that will be created when triggered
        task_description: Description for the generated todo
        task_priority: Priority for the generated todo ('high', 'medium', 'low')
        trigger_at: ISO datetime string for once type (e.g., '2026-05-05T15:00:00')
        cron_expression: Cron expression for recurring type (e.g., '0 9 * * *')
    """
    if not name or not name.strip():
        return "Error: name is required"
    if schedule_type not in ("once", "recurring"):
        return "Error: schedule_type must be 'once' or 'recurring'"
    if task_priority not in ("high", "medium", "low"):
        return "Error: task_priority must be 'high', 'medium', or 'low'"

    if schedule_type == "once" and not trigger_at:
        return "Error: trigger_at is required for once-type schedules"
    if schedule_type == "recurring" and not cron_expression:
        return "Error: cron_expression is required for recurring schedules"

    svc = _get_service()
    st = svc.add(
        name=name.strip(),
        schedule_type=schedule_type,
        task_title=task_title.strip() or name.strip(),
        task_description=task_description.strip(),
        task_priority=task_priority,
        trigger_at=trigger_at or None,
        cron_expression=cron_expression or None,
    )

    # Register with the running scheduler if available
    if _scheduler:
        _scheduler.add_schedule(st)

    return (
        f"Schedule created: [{st.id}] {st.name} "
        f"(type: {st.schedule_type}, enabled: {st.enabled})"
    )


def cron_list(enabled_only: bool = False) -> str:
    """List all scheduled tasks.

    Args:
        enabled_only: If true, only show enabled schedules (default: false, show all)
    """
    svc = _get_service()
    schedules = svc.list(enabled_only=enabled_only)

    if not schedules:
        return "No scheduled tasks found."

    lines = [f"{len(schedules)} schedule(s):"]
    type_icon = {"once": "[1]", "recurring": "[↻]"}
    status_icon = {True: "✓", False: "✗暂停"}

    for s in schedules:
        icon = type_icon.get(s.schedule_type, "[?]")
        status = status_icon.get(s.enabled, "?")
        trigger_info = s.trigger_at if s.schedule_type == "once" else f"cron: {s.cron_expression}"
        last = f" | last: {s.last_triggered}" if s.last_triggered else ""
        lines.append(
            f"  {icon} {status} [{s.id}] {s.name} → '{s.task_title}' "
            f"({trigger_info}, x{s.execution_count}{last})"
        )

    return "\n".join(lines)


def cron_update(schedule_id: str, **kwargs) -> str:
    """Update a scheduled task's configuration.

    Args:
        schedule_id: The schedule ID (from cron_list output)
        **kwargs: Fields to update — name, task_title, task_description,
                  task_priority, trigger_at (for once), cron_expression (for recurring)
    """
    svc = _get_service()
    existing = svc.get(schedule_id)
    if existing is None:
        return f"Error: schedule '{schedule_id}' not found. Use cron_list to see all IDs."

    allowed = (
        "name", "task_title", "task_description", "task_priority",
        "trigger_at", "cron_expression",
    )
    updates = {k: v for k, v in kwargs.items() if k in allowed and v}

    if not updates:
        return "Error: provide at least one field to update"

    if _scheduler:
        st = _scheduler.update_schedule(schedule_id, **updates)
    else:
        st = svc.update(schedule_id, **updates)

    if st is None:
        return f"Error: failed to update schedule '{schedule_id}'"

    return f"Schedule updated: [{st.id}] {st.name}"


def cron_delete(schedule_id: str) -> str:
    """Delete a scheduled task permanently. Already-generated todos are not affected.

    Args:
        schedule_id: The schedule ID to delete
    """
    svc = _get_service()
    st = svc.get(schedule_id)
    if st is None:
        return f"Error: schedule '{schedule_id}' not found."

    name = st.name
    if _scheduler:
        _scheduler.delete_schedule(schedule_id)
    else:
        svc.delete(schedule_id)

    return f"Schedule deleted: [{schedule_id}] {name}"


def cron_pause(schedule_id: str) -> str:
    """Pause a scheduled task — it won't generate any more todos until resumed.

    Args:
        schedule_id: The schedule ID to pause
    """
    svc = _get_service()
    st = svc.get(schedule_id)
    if st is None:
        return f"Error: schedule '{schedule_id}' not found."
    if not st.enabled:
        return f"Schedule '{schedule_id}' is already paused."

    if _scheduler:
        _scheduler.pause_schedule(schedule_id)
    else:
        svc.set_enabled(schedule_id, False)

    return f"Schedule paused: [{schedule_id}] {st.name}"


def cron_resume(schedule_id: str) -> str:
    """Resume a paused scheduled task.

    Args:
        schedule_id: The schedule ID to resume
    """
    svc = _get_service()
    st = svc.get(schedule_id)
    if st is None:
        return f"Error: schedule '{schedule_id}' not found."
    if st.enabled:
        return f"Schedule '{schedule_id}' is already enabled."

    if _scheduler:
        _scheduler.resume_schedule(schedule_id)
    else:
        svc.set_enabled(schedule_id, True)

    return f"Schedule resumed: [{schedule_id}] {st.name}"

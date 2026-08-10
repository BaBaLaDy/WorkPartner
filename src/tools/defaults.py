"""Register all default tools into a ToolRegistry."""

from .registry import ToolRegistry
from .file_ops import file_read, file_write, file_patch
from .code_exec import code_run
from .todo_tools import todo_add, todo_list, todo_update, todo_delete
from .cron_tools import cron_add, cron_list, cron_update, cron_delete, cron_pause, cron_resume
from .web_tools import web_search, web_extract
from .shutdown import shutdown_agent
from .im_tools import im_notify

# Desktop tools require GUI-platform dependencies (pyautogui, pygetwindow...).
# On platforms where they are missing or fail to initialise (e.g. headless
# Linux), skip them instead of breaking startup.
try:
    from .desktop import (
        desktop_screenshot,
        desktop_click,
        desktop_move,
        desktop_drag,
        desktop_scroll,
        desktop_type,
        desktop_press,
        desktop_get_windows,
        desktop_focus_window,
        desktop_get_screen_info,
        desktop_locate,
    )
    HAS_DESKTOP = True
except Exception:
    HAS_DESKTOP = False


def create_default_registry() -> ToolRegistry:
    """Create a ToolRegistry with all default tools.

    SubAgent tools are registered separately by the engine after the agent
    graph is created (to avoid circular imports).
    """
    reg = ToolRegistry()

    reg.register(file_read, read_only=True, max_result_chars=12000, tags=("filesystem",))
    reg.register(
        file_write,
        read_only=False,
        destructive=True,
        requires_permission=True,
        tags=("filesystem", "write"),
    )
    reg.register(
        file_patch,
        read_only=False,
        destructive=True,
        requires_permission=True,
        tags=("filesystem", "write"),
    )
    reg.register(
        code_run,
        read_only=False,
        destructive=True,
        requires_permission=True,
        concurrency_safe=False,
        max_result_chars=10000,
        tags=("code", "process"),
    )

    reg.register(todo_add, read_only=False, tags=("todo",))
    reg.register(todo_list, read_only=True, tags=("todo",))
    reg.register(todo_update, read_only=False, tags=("todo",))
    reg.register(
        todo_delete,
        read_only=False,
        destructive=True,
        requires_permission=True,
        tags=("todo",),
    )

    # Desktop tools — Windows-only, skip on Linux/server
    if HAS_DESKTOP:
        # Desktop observation tools.
        reg.register(
            desktop_screenshot,
            read_only=True,
            max_result_chars=0,
            tags=("desktop", "vision"),
        )
        reg.register(desktop_get_windows, read_only=True, tags=("desktop", "window"))
        reg.register(desktop_get_screen_info, read_only=True, tags=("desktop",))
        reg.register(
            desktop_locate,
            read_only=True,
            concurrency_safe=False,
            tags=("desktop", "vision"),
        )

        # Desktop action tools.
        reg.register(
            desktop_click,
            read_only=False,
            requires_permission=True,
            concurrency_safe=False,
            tags=("desktop", "mouse"),
        )
        reg.register(
            desktop_move,
            read_only=False,
            requires_permission=True,
            concurrency_safe=False,
            tags=("desktop", "mouse"),
        )
        reg.register(
            desktop_drag,
            read_only=False,
            requires_permission=True,
            concurrency_safe=False,
            tags=("desktop", "mouse"),
        )
        reg.register(
            desktop_scroll,
            read_only=False,
            requires_permission=True,
            concurrency_safe=False,
            tags=("desktop", "mouse"),
        )
        reg.register(
            desktop_type,
            read_only=False,
            requires_permission=True,
            concurrency_safe=False,
            tags=("desktop", "keyboard"),
        )
        reg.register(
            desktop_press,
            read_only=False,
            requires_permission=True,
            concurrency_safe=False,
            tags=("desktop", "keyboard"),
        )
        reg.register(
            desktop_focus_window,
            read_only=False,
            requires_permission=True,
            concurrency_safe=False,
            tags=("desktop", "window"),
        )

    # Web tools: search and extraction are read-only but can produce large output.
    reg.register(web_search, read_only=True, max_result_chars=12000, tags=("web",))
    reg.register(web_extract, read_only=True, max_result_chars=20000, tags=("web",))

    # Cron schedule tools.
    reg.register(
        cron_add,
        read_only=False,
        requires_permission=True,
        tags=("schedule",),
    )
    reg.register(cron_list, read_only=True, tags=("schedule",))
    reg.register(
        cron_update,
        read_only=False,
        requires_permission=True,
        tags=("schedule",),
    )
    reg.register(
        cron_delete,
        read_only=False,
        destructive=True,
        requires_permission=True,
        tags=("schedule",),
    )
    reg.register(
        cron_pause,
        read_only=False,
        requires_permission=True,
        tags=("schedule",),
    )
    reg.register(
        cron_resume,
        read_only=False,
        requires_permission=True,
        tags=("schedule",),
    )

    reg.register(
        shutdown_agent,
        read_only=False,
        destructive=True,
        requires_permission=True,
        concurrency_safe=False,
        tags=("runtime",),
    )
    reg.register(
        im_notify,
        read_only=False,
        requires_permission=True,
        tags=("im", "external"),
    )

    return reg

"""Shutdown tool — allows the agent to gracefully terminate the host process."""

_shutdown_requested = False


def shutdown_agent(reason: str = "Agent requested shutdown") -> str:
    """Gracefully shut down the agent process.

    The agent will terminate after completing this response.
    All pending operations (schedulers, bridges) will be cleaned up.
    """
    global _shutdown_requested
    _shutdown_requested = True
    return f"Shutdown requested: {reason}. Process will exit after this message."


def is_shutdown_requested() -> bool:
    return _shutdown_requested


def reset_shutdown_flag() -> None:
    """Reset the flag (useful for testing / session reset)."""
    global _shutdown_requested
    _shutdown_requested = False

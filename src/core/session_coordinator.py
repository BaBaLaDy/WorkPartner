"""SessionCoordinator — unified session lifecycle API.

Wraps SessionManager + AgentSession to provide a single entry point
for session creation, restoration, and closure with metadata injection.

Design: Coordinator handles metadata (session_type/owner/etc.) injection
at creation time. AgentSession still owns internal assembly (model/tools/graph).
Phase 5: close() triggers memory.summarize_session() for interactive sessions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from src.agent.session import AgentSession
    from src.agent.session_manager import SessionManager


class SessionCoordinator:
    """Coordinates session lifecycle with metadata.

    All entry points (CLI, Web UI, Bridge) use this class to create
    sessions instead of calling AgentSession directly.
    """

    def __init__(self, session_manager: "SessionManager",
                 get_memory: Callable[[], Any] | None = None):
        self._sm = session_manager
        self._get_memory = get_memory

    # -- Session creation --

    def create(
        self,
        session_type: str = "interactive",
        owner: str = "cli",
        workspace_scope: str = "",
        permission_mode: str = "operate",
        task_id: str | None = None,
        parent_schedule_id: str | None = None,
    ) -> "AgentSession":
        """Create a new session with metadata.

        Args:
            session_type: "interactive" | "bridge" | "managed" | "cron"
            owner: "cli" | "ui" | "telegram" | "feishu" | "scheduler"
            workspace_scope: workspace root path
            permission_mode: "read_only" | "ask" | "operate"
            task_id: linked todo id (for managed sessions)
            parent_schedule_id: schedule that triggered this (for cron sessions)

        Returns:
            Configured AgentSession instance.
        """
        from src.agent.session import AgentSession

        # Create session in SessionManager with metadata
        thread_id = self._sm.create_session(
            name=f"{owner}-{session_type}",
            session_type=session_type,
            owner=owner,
        )

        # Create AgentSession with metadata parameters
        memory = self._get_memory() if self._get_memory is not None else None
        session = AgentSession(
            session_manager=self._sm,
            session_type=session_type,
            owner=owner,
            workspace_scope=workspace_scope,
            permission_mode=permission_mode,
            memory_manager=memory,
        )
        return session

    # -- Session close --

    def close(self, session: "AgentSession", run_status: str = "done"):
        """Mark a session as closed with final status.

        For interactive sessions, triggers memory summarization.
        """
        # Update metadata in state (for checkpoint persistence)
        session._run_status = run_status

        # Trigger memory summarization for interactive sessions
        if session._session_type == "interactive" and self._get_memory is not None:
            memory = self._get_memory()
            if memory is not None:
                try:
                    # Run async summarize in event loop if available
                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            loop.create_task(
                                memory.summarize_session(session._get_messages())
                            )
                        else:
                            loop.run_until_complete(
                                memory.summarize_session(session._get_messages())
                            )
                    except RuntimeError:
                        asyncio.run(
                            memory.summarize_session(session._get_messages())
                        )
                except Exception:
                    # Memory summarization should not break session close
                    pass

    # -- Accessor --

    @property
    def session_manager(self) -> "SessionManager":
        return self._sm

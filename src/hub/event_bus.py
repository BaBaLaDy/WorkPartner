"""EventBus: async pub/sub for canonical AgentEvent envelopes."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine

from .events import AgentEvent

logger = logging.getLogger(__name__)

Callback = Callable[[AgentEvent], Coroutine[None, None, None]]


class EventBus:
    """Async event bus with multi-subscriber support.

    All emitted data is normalized into ``AgentEvent`` before it reaches UI,
    supervisor, or logs. Payloads remain plain dictionaries for compatibility.
    """

    def __init__(self):
        self._subscribers: dict[str, list[Callback]] = {}
        self._all_subscribers: list[Callback] = []

    def subscribe(self, event_name: str, callback: Callback) -> None:
        """Register a callback for one event type."""
        self._subscribers.setdefault(event_name, []).append(callback)

    def subscribe_all(self, callback: Callback) -> None:
        """Register a callback for every event."""
        self._all_subscribers.append(callback)

    def unsubscribe(self, event_name: str, callback: Callback) -> None:
        """Remove a specific callback for an event."""
        callbacks = self._subscribers.get(event_name, [])
        if callback in callbacks:
            callbacks.remove(callback)

    def unsubscribe_all(self, callback: Callback) -> None:
        """Remove a callback from the all-event stream."""
        if callback in self._all_subscribers:
            self._all_subscribers.remove(callback)

    async def emit(
        self,
        event_name: str,
        data: dict[str, Any] | AgentEvent | None = None,
        **metadata: Any,
    ) -> AgentEvent:
        """Fire an event and return the normalized AgentEvent."""
        event = AgentEvent.normalize(event_name, data, **metadata)
        callbacks = [
            *self._subscribers.get(event.type, []),
            *self._all_subscribers,
        ]
        if not callbacks:
            return event
        results = await asyncio.gather(
            *(cb(event) for cb in callbacks),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.error("EventBus subscriber error on '%s': %s", event.type, result)
        return event

    # Agent events
    THINKING_DELTA = "thinking_delta"
    TEXT_DELTA = "text_delta"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"

    # Task lifecycle
    TASK_ADDED = "task.added"
    TASK_CREATED = "task.created"
    TASK_STARTED = "task.started"
    TASK_PROGRESS = "task.progress"
    TASK_DONE = "task.done"
    TASK_FAILED = "task.failed"
    TASK_RETRYING = "task.retrying"
    TASK_CANCELLED = "task.cancelled"

    # Executor / supervisor
    EXECUTOR_WAKEUP = "executor.wakeup"
    SUPERVISOR_UPDATED = "supervisor.updated"

    # Role / subagent lifecycle
    ROLE_STARTED = "role.started"
    ROLE_DONE = "role.done"
    ROLE_FAILED = "role.failed"

    # System
    SESSION_CREATED = "session.created"
    SESSION_CLOSED = "session.closed"
    MEMORY_UPDATED = "memory.updated"

    # Pin
    PIN_CREATED = "pin.created"
    PIN_UPDATED = "pin.updated"

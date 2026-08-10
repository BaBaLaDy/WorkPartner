"""WebSocket bridge — connects EventBus to WebSocket clients."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket
from src.hub.event_bus import EventBus
from src.hub.events import AgentEvent

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections and bridges EventBus events."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self._event_bus: EventBus | None = None

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active_connections.append(ws)
        logger.info("WebSocket connected. Total: %d", len(self.active_connections))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active_connections:
            self.active_connections.remove(ws)
        logger.info("WebSocket disconnected. Total: %d", len(self.active_connections))

    async def broadcast(self, data: dict[str, Any] | AgentEvent, event_name: str | None = None) -> None:
        """Broadcast an event to all connected clients.

        Sends the canonical AgentEvent envelope plus legacy aliases:
        ``event``/``data`` for older frontend code, ``type``/``payload`` for
        event-stream consumers.
        """
        if isinstance(data, AgentEvent):
            event = data
        else:
            event = AgentEvent.normalize(event_name or "unknown", data)

        message = json.dumps(event.to_wire(), ensure_ascii=False)
        dead = []
        for conn in self.active_connections:
            try:
                await conn.send_text(message)
            except Exception:
                dead.append(conn)
        for d in dead:
            self.disconnect(d)

    def subscribe_to_event_bus(self, event_bus: EventBus) -> None:
        """Subscribe this manager to all events on the given EventBus."""
        self._event_bus = event_bus
        for event_name in [
            EventBus.TASK_CREATED,
            EventBus.TASK_STARTED,
            EventBus.TASK_PROGRESS,
            EventBus.TASK_DONE,
            EventBus.TASK_FAILED,
            EventBus.TASK_RETRYING,
            EventBus.TASK_CANCELLED,
            EventBus.TOOL_START,
            EventBus.TOOL_END,
            EventBus.THINKING_DELTA,
            EventBus.TEXT_DELTA,
            EventBus.EXECUTOR_WAKEUP,
            EventBus.SUPERVISOR_UPDATED,
            EventBus.ROLE_STARTED,
            EventBus.ROLE_DONE,
            EventBus.ROLE_FAILED,
        ]:
            event_bus.subscribe(event_name, self._make_event_handler(event_name))

    def _make_event_handler(self, event_name: str):
        async def _handler(event: AgentEvent) -> None:
            await self.broadcast(event, event_name=event_name)
        return _handler

    async def _event_handler(self, data: dict[str, Any] | AgentEvent) -> None:
        """Handler called by EventBus for each event."""
        await self.broadcast(data)

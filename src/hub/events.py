"""Structured event envelope used across the agent runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class AgentEvent(BaseModel):
    """Canonical event shape for UI, supervisor, and logs."""

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    parent_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    agent_id: str = "workpartner"
    caller: str = "system"

    @property
    def event(self) -> str:
        """Legacy alias for frontend code that still reads ``event``."""
        return self.type

    @property
    def data(self) -> dict[str, Any]:
        """Legacy alias for frontend code that still reads ``data``."""
        return self.payload

    def to_wire(self) -> dict[str, Any]:
        """Return a WebSocket-friendly envelope with legacy aliases."""
        data = self.model_dump()
        data["event"] = self.type
        data["data"] = self.payload
        return data

    @classmethod
    def normalize(
        cls,
        event_type: str,
        data: dict[str, Any] | "AgentEvent" | None = None,
        *,
        trace_id: str | None = None,
        parent_id: str | None = None,
        session_id: str | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        caller: str | None = None,
    ) -> "AgentEvent":
        """Create an AgentEvent from raw or pre-wrapped event data."""
        if isinstance(data, AgentEvent):
            return data

        raw = dict(data or {})

        # Accept old pre-wrapped form: {"event": "...", "data": {...}}.
        if isinstance(raw.get("data"), dict):
            event_type = str(raw.get("event") or raw.get("type") or event_type)
            payload = dict(raw["data"])
            timestamp = raw.get("timestamp")
        else:
            payload = raw
            timestamp = raw.get("timestamp")

        event_id = payload.pop("event_id", raw.get("event_id", None)) or uuid4().hex
        resolved_trace_id = (
            trace_id
            or payload.pop("trace_id", None)
            or raw.get("trace_id")
            or event_id
        )
        resolved_parent_id = parent_id or payload.pop("parent_id", None) or raw.get("parent_id")
        resolved_session_id = session_id or payload.get("session_id") or raw.get("session_id")
        resolved_task_id = task_id or payload.get("task_id") or raw.get("task_id")
        resolved_agent_id = agent_id or payload.pop("agent_id", None) or raw.get("agent_id") or "workpartner"
        resolved_caller = caller or payload.pop("caller", None) or raw.get("caller") or "system"

        return cls(
            event_id=event_id,
            type=event_type,
            payload=payload,
            timestamp=str(timestamp or datetime.now(timezone.utc).isoformat()),
            trace_id=str(resolved_trace_id),
            parent_id=resolved_parent_id,
            session_id=resolved_session_id,
            task_id=resolved_task_id,
            agent_id=str(resolved_agent_id),
            caller=str(resolved_caller),
        )

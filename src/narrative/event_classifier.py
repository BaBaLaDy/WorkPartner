"""Event classifier — converts raw AgentEvent to structured summaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.hub.events import AgentEvent


@dataclass
class StructuredSummary:
    """Canonical structured representation of an office event."""

    action: str            # e.g. "start", "complete", "fail", "handoff"
    actor: str             # role display_name
    actor_role: str        # role internal name (e.g. "researcher")
    task: str = ""         # task title or description
    urgency: str = "normal"  # "normal" | "high" | "low"
    quality: str = ""      # "pass" | "fail" | ""
    error: str = ""        # error summary for failures
    next_actor: str = ""   # target of handoff, if any
    raw: dict[str, Any] | None = None  # original payload for fallback


class EventClassifier:
    """Rule-based classifier that maps AgentEvent to StructuredSummary."""

    ROLE_EVENT_MAP = {
        "role.started": "_classify_role_started",
        "role.done": "_classify_role_done",
        "role.failed": "_classify_role_failed",
    }

    TASK_EVENT_MAP = {
        "task.done": "_classify_task_done",
        "task.failed": "_classify_task_failed",
        "task.created": "_classify_task_created",
        "task.started": "_classify_task_started",
        "task.cancelled": "_classify_task_cancelled",
    }

    def classify(self, event: AgentEvent, *, role_loader=None) -> StructuredSummary:
        """Classify an AgentEvent into a StructuredSummary.

        Args:
            event: The AgentEvent to classify.
            role_loader: Optional RoleLoader for resolving role display names.
        """
        event_type = event.type
        handler_name = self.ROLE_EVENT_MAP.get(event_type) or self.TASK_EVENT_MAP.get(event_type)

        if handler_name:
            handler = getattr(self, handler_name)
            return handler(event, role_loader=role_loader)

        return self._classify_generic(event)

    def _resolve_actor(self, event: AgentEvent, role_loader) -> tuple[str, str]:
        """Return (display_name, role_name) from event metadata."""
        payload = event.payload
        role_name = payload.get("role", "")
        display_name = role_name

        if role_loader and role_name:
            role = role_loader.get(role_name)
            if role:
                display_name = role.display_name

        return display_name, role_name

    def _classify_role_started(self, event: AgentEvent, *, role_loader=None) -> StructuredSummary:
        display_name, role_name = self._resolve_actor(event, role_loader)
        return StructuredSummary(
            action="start",
            actor=display_name,
            actor_role=role_name,
            task=event.payload.get("title", ""),
            urgency="normal",
            raw=event.payload,
        )

    def _classify_role_done(self, event: AgentEvent, *, role_loader=None) -> StructuredSummary:
        display_name, role_name = self._resolve_actor(event, role_loader)
        return StructuredSummary(
            action="complete",
            actor=display_name,
            actor_role=role_name,
            task=event.payload.get("title", ""),
            quality=event.payload.get("quality", "pass"),
            urgency="normal",
            raw=event.payload,
        )

    def _classify_role_failed(self, event: AgentEvent, *, role_loader=None) -> StructuredSummary:
        display_name, role_name = self._resolve_actor(event, role_loader)
        return StructuredSummary(
            action="fail",
            actor=display_name,
            actor_role=role_name,
            task=event.payload.get("title", ""),
            error=event.payload.get("error", ""),
            urgency="high",
            raw=event.payload,
        )

    def _classify_task_done(self, event: AgentEvent, *, role_loader=None) -> StructuredSummary:
        display_name, role_name = self._resolve_actor(event, role_loader)
        return StructuredSummary(
            action="complete",
            actor=display_name,
            actor_role=role_name,
            task=event.payload.get("title", ""),
            quality=event.payload.get("quality_status", "pass"),
            urgency="normal",
            raw=event.payload,
        )

    def _classify_task_failed(self, event: AgentEvent, *, role_loader=None) -> StructuredSummary:
        display_name, role_name = self._resolve_actor(event, role_loader)
        return StructuredSummary(
            action="fail",
            actor=display_name,
            actor_role=role_name,
            task=event.payload.get("title", ""),
            error=event.payload.get("error", ""),
            urgency="high",
            raw=event.payload,
        )

    def _classify_task_created(self, event: AgentEvent, *, role_loader=None) -> StructuredSummary:
        display_name, role_name = self._resolve_actor(event, role_loader)
        return StructuredSummary(
            action="create",
            actor=display_name or "system",
            actor_role=role_name or "system",
            task=event.payload.get("title", ""),
            urgency="low",
            raw=event.payload,
        )

    def _classify_task_started(self, event: AgentEvent, *, role_loader=None) -> StructuredSummary:
        display_name, role_name = self._resolve_actor(event, role_loader)
        return StructuredSummary(
            action="start",
            actor=display_name or "system",
            actor_role=role_name or "system",
            task=event.payload.get("title", ""),
            urgency="normal",
            raw=event.payload,
        )

    def _classify_task_cancelled(self, event: AgentEvent, *, role_loader=None) -> StructuredSummary:
        display_name, role_name = self._resolve_actor(event, role_loader)
        return StructuredSummary(
            action="cancel",
            actor=display_name or "system",
            actor_role=role_name or "system",
            task=event.payload.get("title", ""),
            urgency="low",
            raw=event.payload,
        )

    def _classify_generic(self, event: AgentEvent) -> StructuredSummary:
        """Fallback for unclassified event types."""
        return StructuredSummary(
            action=event.type,
            actor=event.payload.get("role", event.payload.get("actor", "system")),
            actor_role=event.payload.get("role", ""),
            task=event.payload.get("title", ""),
            urgency="normal",
            raw=event.payload,
        )

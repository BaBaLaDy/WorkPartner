"""Pydantic models for API request/response validation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from typing_extensions import Literal


# -- Task schemas --

class TaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str = ""
    priority: Literal["high", "medium", "low"] = "medium"
    role: str | None = None  # optional role name for execution
    auto_run: bool = True  # whether to immediately execute or queue as pending


class TaskUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    status: Literal["pending", "in_progress", "done", "cancelled"] | None = None
    priority: Literal["high", "medium", "low"] | None = None


# -- Schedule schemas --

class ScheduleCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    type: Literal["once", "recurring"]
    cron_expression: str | None = None
    trigger_at: str | None = None  # ISO 8601 timestamp for type="once"
    task_description: str = ""


class ScheduleUpdateRequest(BaseModel):
    title: str | None = None
    cron_expression: str | None = None
    enabled: bool | None = None


# -- Chat schemas --

class ChatMessageRequest(BaseModel):
    message: str = Field(..., min_length=1)
    managed_mode: bool = False
    thread_id: str | None = None


# -- Status schemas --

class ServerStatus(BaseModel):
    running: bool
    pending_tasks: int
    active_schedules: int
    websocket_connections: int


# -- WebSocket event envelope --

class WsEvent(BaseModel):
    event_id: str | None = None
    type: str | None = None
    payload: dict[str, Any] | None = None
    trace_id: str | None = None
    parent_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    agent_id: str | None = None
    caller: str | None = None
    event: str
    data: dict[str, Any]
    timestamp: str


# -- Office state schemas --

class ActiveMember(BaseModel):
    name: str
    status: str  # "idle" | "busy" | etc.
    task: str | None = None


class PendingAttentionItem(BaseModel):
    task_id: str
    reason: str
    retry_count: int = 0


class OfficeStateResponse(BaseModel):
    office_mood: str  # "idle" | "busy" | "attention_needed"
    active_members: list[ActiveMember] = []
    recent_handovers: list[str] = []
    pending_attention: list[PendingAttentionItem] = []
    suggested_next_action: str | None = None


# -- Role schemas --

class RoleSummary(BaseModel):
    name: str
    display_name: str
    description: str
    icon: str
    personality: str = ""
    greeting: str = ""
    signoff: str = ""
    status_text: str = ""
    tone: str = ""
    idle_style: str = ""
    busy_style: str = ""
    success_style: str = ""
    failure_style: str = ""
    handoff_style: str = ""


class RoleDetail(BaseModel):
    name: str
    display_name: str
    description: str
    icon: str
    system_prompt: str
    tools: list[str] | None = None
    model: str | None = None
    personality: str = ""
    greeting: str = ""
    signoff: str = ""
    status_text: str = ""
    tone: str = ""
    idle_style: str = ""
    busy_style: str = ""
    success_style: str = ""
    failure_style: str = ""
    handoff_style: str = ""


class RoleListResponse(BaseModel):
    roles: list[RoleSummary]


class RoleDetailResponse(BaseModel):
    role: RoleDetail


class RoleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    display_name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., max_length=500)
    icon: str = "🤖"
    system_prompt: str = Field(..., min_length=1)
    tools: list[str] | None = None
    model: str | None = None
    personality: str = ""
    greeting: str = ""
    signoff: str = ""
    status_text: str = ""
    tone: str = ""
    idle_style: str = ""
    busy_style: str = ""
    success_style: str = ""
    failure_style: str = ""
    handoff_style: str = ""


class RoleUpdateRequest(BaseModel):
    name: str | None = None  # renaming
    display_name: str | None = None
    description: str | None = None
    icon: str | None = None
    system_prompt: str | None = None
    tools: list[str] | None = None
    model: str | None = None
    personality: str | None = None
    greeting: str | None = None
    signoff: str | None = None
    status_text: str | None = None
    tone: str | None = None
    idle_style: str | None = None
    busy_style: str | None = None
    success_style: str | None = None
    failure_style: str | None = None
    handoff_style: str | None = None


# -- Pin schemas --

class PinResponse(BaseModel):
    thread_id: str
    title: str
    summary: str
    status: str  # "done" | "failed" | "waiting_confirm"
    created_at: str
    read: bool
    task_id: str = ""


class PinListResponse(BaseModel):
    pins: list[PinResponse]
    unread_count: int

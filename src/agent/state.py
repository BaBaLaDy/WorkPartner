from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class AgentState(TypedDict, total=False):
    """LangGraph agent state.

    messages: conversation history, auto-merged via add_messages reducer.
    system_prompt: the full system prompt (skills may be injected per turn).
    tools: available tool schemas.
    compression_summary: when set, replaces older messages to save context.

    Session metadata (Phase 2): all have safe defaults for backward compat.
    """

    # Core fields (required)
    messages: Annotated[list[BaseMessage], add_messages]
    system_prompt: str
    tools: list[dict]
    compression_summary: str | None

    # Session metadata (optional — default to None/"")
    session_type: str           # "interactive" | "bridge" | "managed" | "cron"
    owner: str                  # "cli" | "ui" | "telegram" | "feishu" | "scheduler"
    workspace_scope: str        # workspace root path
    permission_mode: str        # "read_only" | "ask" | "operate"
    task_id: str | None         # linked todo id (managed sessions)
    parent_schedule_id: str | None  # schedule that triggered this (cron sessions)
    run_status: str             # "running" | "paused" | "done" | "failed"
    failure_count: int          # retry counter
    last_tool_summary: str      # recent tool execution summary for audit
    pin: dict | None            # pin data for homepage: {summary, status, created_at, read}

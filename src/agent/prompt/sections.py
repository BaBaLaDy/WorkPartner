"""Section renderers for PromptAssembler.

Each renderer is a pure function: accepts params dict, returns str.
Empty or missing params → returns empty string.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Stable sections (high cache hit)
# ---------------------------------------------------------------------------

def render_role_header(params: dict[str, Any]) -> str:
    """Role definition: display name + system prompt (markdown body)."""
    role = params.get("role")
    if role is None:
        return ""
    return f"# Role: {role.display_name}\n\n{role.system_prompt}"


def render_base_rules(params: dict[str, Any]) -> str:
    """Base system prompt: rules + decision table + skill reference."""
    base = params.get("base_rules", "")
    return base


def render_role_presence(params: dict[str, Any]) -> str:
    """Role working-style guidance (tone, styles, greeting, etc.)."""
    from src.roles.loader import build_role_presence
    role = params.get("role")
    if role is None:
        return ""
    presence = build_role_presence(role)
    if not presence:
        return ""
    return "## Role presence\n" + presence


def render_skills(params: dict[str, Any]) -> str:
    """L1 skill metadata + L2 instructions if matched."""
    injector = params.get("injector")
    user_message = params.get("user_message", "")
    if injector is None:
        return ""
    parts = []
    l1 = injector.build_skills_prompt()
    if l1:
        parts.append(l1)
    if user_message:
        l2 = injector.match_and_inject(user_message)
        if l2:
            parts.append(
                "---\n# The following skill instructions apply to this conversation:\n\n" + l2
            )
    return "\n\n".join(parts)


def render_subagent_rules(params: dict[str, Any]) -> str:
    """SubAgent-specific rules (hardcoded)."""
    return params.get("subagent_rules", "")


def render_thinking_protocol(params: dict[str, Any]) -> str:
    """Thinking protocol for SubAgent sessions."""
    return params.get("thinking_protocol", "")


def render_team_delegation(params: dict[str, Any]) -> str:
    """Team delegation section for managed sessions."""
    return params.get("team_delegation", "")


def render_supervisor_rules(params: dict[str, Any]) -> str:
    """Supervisor-specific rules section."""
    return params.get("supervisor_rules", "")


# ---------------------------------------------------------------------------
# Volatile sections (low cache hit — must appear last)
# ---------------------------------------------------------------------------

def render_conversation_mode(params: dict[str, Any]) -> str:
    """Session-local interaction mode (rushed/frustrated/etc.)."""
    user_message = params.get("user_message", "")
    return _build_conversation_mode_prompt(user_message)


def _build_conversation_mode_prompt(user_message: str) -> str:
    """Inline copy from session.py to avoid circular import (session → defaults → desktop → pyautogui)."""
    mode = _detect_conversation_mode(user_message)
    if mode is None:
        return ""
    return (
        "## Conversation mode\n"
        f"- Current mode: {mode['label']}\n"
        f"- Guidance: {mode['guidance']}"
    )


def _detect_conversation_mode(user_message: str) -> dict[str, str] | None:
    """Lightweight mode detection — inline to avoid importing session.py."""
    text = (user_message or "").strip().lower()
    if not text:
        return None
    rules = [
        (("着急", "赶紧", "尽快", "马上", "asap", "urgent", "quickly"),
         {"mode": "rushed", "label": "Rushed",
          "guidance": "Keep the response short, front-load the answer, and avoid decorative phrasing."}),
        (("烦", "糟", "崩", "失败", "卡住", "annoyed", "frustrated", "stuck", "blocked"),
         {"mode": "frustrated", "label": "Frustrated",
          "guidance": "Acknowledge the blockage plainly and focus on recovery steps."}),
        (("累", "疲惫", "没精神", "深夜", "困", "tired", "exhausted", "sleepy"),
         {"mode": "low_energy", "label": "Low energy",
          "guidance": "Use low-friction wording and prefer direct execution."}),
        (("不知道", "帮我想", "犹豫", "not sure", "help me think", "unsure"),
         {"mode": "exploratory", "label": "Exploratory",
          "guidance": "Frame tradeoffs clearly and offer a recommendation."}),
        (("谢谢", "辛苦", "不错", "太好了", "thanks", "great", "nice"),
         {"mode": "positive", "label": "Positive",
          "guidance": "Keep the tone warm but restrained. Move cleanly to the next action."}),
    ]
    for keywords, mode in rules:
        if any(kw in text for kw in keywords):
            return mode
    return None


def render_memory(params: dict[str, Any]) -> str:
    """Memory section from MemoryManager."""
    memory_manager = params.get("memory_manager")
    session_type = params.get("session_type", "interactive")
    if memory_manager is None:
        return ""
    return memory_manager.assemble_memory(session_type=session_type)


def render_role_memory(params: dict[str, Any]) -> str:
    """Role-specific memory (used in subagent sessions)."""
    memory_manager = params.get("memory_manager")
    role = params.get("role")
    if memory_manager is None or role is None:
        return ""
    return memory_manager.assemble_role_memory(role.name)


def render_runtime(params: dict[str, Any]) -> str:
    """Single-line runtime context: now, os, cwd."""
    import os
    import platform
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tz = datetime.now().astimezone().strftime("%Z")
    return f"<runtime>now={now} {tz} | os={platform.system()} | cwd={os.getcwd()}</runtime>"


def render_daily_log(params: dict[str, Any]) -> str:
    """Supervisor daily log section."""
    memory_manager = params.get("memory_manager")
    if memory_manager is None:
        return ""
    return memory_manager.assemble_supervisor_memory().get("daily_log", "")


def render_insights(params: dict[str, Any]) -> str:
    """Supervisor insights section."""
    memory_manager = params.get("memory_manager")
    if memory_manager is None:
        return ""
    return memory_manager.assemble_supervisor_memory().get("insights", "")


def render_action_items(params: dict[str, Any]) -> str:
    """Supervisor action items section."""
    memory_manager = params.get("memory_manager")
    if memory_manager is None:
        return ""
    return memory_manager.assemble_supervisor_memory().get("action_items", "")


def render_user_prefs(params: dict[str, Any]) -> str:
    """User preferences section (supervisor sessions)."""
    memory_manager = params.get("memory_manager")
    if memory_manager is None:
        return ""
    return memory_manager.assemble_supervisor_memory().get("user_prefs", "")

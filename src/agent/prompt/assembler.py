"""PromptAssembler — unified system prompt assembly.

Single entry point: given a profile + params, return a complete system prompt
string with cache-aware section ordering (stable prefix, volatile suffix).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from . import sections as _sections
from .profiles import get_ordered_sections

logger = logging.getLogger(__name__)

# Map section names to renderer functions
_RENDERERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "role_header": _sections.render_role_header,
    "base_rules": _sections.render_base_rules,
    "role_presence": _sections.render_role_presence,
    "skills": _sections.render_skills,
    "subagent_rules": _sections.render_subagent_rules,
    "thinking_protocol": _sections.render_thinking_protocol,
    "team_delegation": _sections.render_team_delegation,
    "supervisor_rules": _sections.render_supervisor_rules,
    "conversation_mode": _sections.render_conversation_mode,
    "memory": _sections.render_memory,
    "role_memory": _sections.render_role_memory,
    "runtime": _sections.render_runtime,
    "daily_log": _sections.render_daily_log,
    "insights": _sections.render_insights,
    "action_items": _sections.render_action_items,
    "user_prefs": _sections.render_user_prefs,
}


class PromptAssembler:
    """Assemble system prompts from profile + parameters."""

    def assemble(self, profile: str, **params: Any) -> str:
        """Assemble a complete system prompt.

        Args:
            profile: One of "interactive", "managed", "subagent", "supervisor".
            **params: Arbitrary parameters forwarded to section renderers.
                Common keys: role, base_rules, memory_manager, injector,
                user_message, session_type, team_delegation, etc.

        Returns:
            Complete system prompt string.
        """
        section_names = get_ordered_sections(profile)
        rendered = []

        for name in section_names:
            renderer = _RENDERERS.get(name)
            if renderer is None:
                logger.warning("No renderer for section: %s", name)
                continue
            try:
                text = renderer(params)
                if text:
                    rendered.append(text)
                    logger.debug(
                        "Section %s: %d chars (stable=%s)",
                        name, len(text),
                        name in ("role_header", "base_rules", "role_presence", "skills"),
                    )
            except Exception:
                logger.exception("Failed to render section: %s", name)

        return "\n\n".join(rendered)

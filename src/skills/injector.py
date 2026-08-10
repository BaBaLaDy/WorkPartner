"""Skill injector — OpenClaw-style XML listing + model-driven loading.

Design (aligned with OpenClaw / Claude Code):
  1. System prompt contains <available_skills> XML block with metadata only
  2. Model scans the block and decides which skill (if any) is relevant
  3. Model calls file_read(location) to load the full SKILL.md body (L2)
  4. Model then follows the skill's instructions exactly

  Only when the user *explicitly names* a skill ("use the pdf skill",
  "/pdf") do we auto-inject the full body — this is the explicit trigger
  path that skips the model's decision step.
"""

from .loader import SkillLoader, Skill


class SkillInjector:
    """Injects skill metadata in OpenClaw XML format + handles explicit triggers."""

    def __init__(self, loader: SkillLoader):
        self.loader = loader
        # Track which skills have already been loaded this session
        self._loaded_in_session: set[str] = set()

    # ── L1: metadata listing (always in system prompt) ──────────────

    def build_skills_prompt(self) -> str:
        """Build L1 metadata block in OpenClaw XML format.

        Only name + description + location. The model reads location
        on-demand when it determines a skill matches the task.
        """
        skills = self.loader.list_all()
        auto_loadable = [s for s in skills if s.should_auto_load]
        manual_only = [s for s in skills if not s.should_auto_load]

        if not skills:
            return ""

        lines = ["<available_skills>"]

        for skill in auto_loadable:
            lines.append("  <skill>")
            lines.append(f"    <name>{skill.name}</name>")
            # Escape XML special chars in description
            desc = self._xml_escape(skill.description)
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>skills/{skill.name}/SKILL.md</location>")
            if skill.version:
                lines.append(f"    <version>{skill.version}</version>")
            lines.append("  </skill>")

        for skill in manual_only:
            lines.append("  <skill user_invocable_only=\"true\">")
            lines.append(f"    <name>{skill.name}</name>")
            lines.append(f"    <description>{self._xml_escape(skill.description)}</description>")
            lines.append(f"    <location>skills/{skill.name}/SKILL.md</location>")
            lines.append("  </skill>")

        lines.append("</available_skills>")
        return "\n".join(lines)

    @staticmethod
    def _xml_escape(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # ── L2: explicit trigger injection (only when user names the skill) ──

    def match_and_inject(self, user_message: str) -> str:
        """Only inject when the user explicitly names a skill.

        This is much more conservative than the previous keyword matching.
        It only fires when the skill name appears verbatim in the message
        — effectively treating it like a slash-command.

        OpenClaw/Claude Code don't do any auto-injection at all; this is
        our pragmatic shortcut for users who explicitly say "use the X skill".
        """
        skills = self.loader.list_all()
        msg_lower = user_message.lower()

        matched = None
        for skill in skills:
            if not skill.should_auto_load:
                continue
            if skill.name in self._loaded_in_session:
                continue
            # Only match when the skill name appears as a word
            if _explicit_mention(skill.name, msg_lower):
                matched = skill
                break

        if not matched:
            return ""

        self._loaded_in_session.add(matched.name)
        return self.format_skill_for_prompt(matched)

    # ── L2: on-demand (called when model reads SKILL.md via file_read) ──

    def get_skill_instructions(self, skill_name: str) -> str | None:
        """Get full SKILL.md body. Model calls this path implicitly by
        using file_read on the <location> from the XML block."""
        skill = self.loader.get(skill_name)
        if not skill:
            return None
        self._loaded_in_session.add(skill_name)
        return self.format_skill_for_prompt(skill)

    def format_skill_for_prompt(self, skill: Skill) -> str:
        """Format a skill's full instructions for injection when loaded."""
        parts = [
            f"# Loaded Skill: `{skill.name}`",
            f"> {skill.description}",
            f"Location: skills/{skill.name}/SKILL.md",
            "",
            skill.content,
        ]
        if skill.allowed_tools:
            parts.append(f"\nAllowed tools: {skill.allowed_tools}")
        return "\n".join(parts)

    def mark_loaded(self, skill_name: str):
        """Mark a skill as loaded (e.g., after the model file_reads it)."""
        self._loaded_in_session.add(skill_name)

    def reset_session(self):
        """Clear the loaded-skill tracking for a new session."""
        self._loaded_in_session.clear()


def _explicit_mention(skill_name: str, msg_lower: str) -> bool:
    r"""Check if the user explicitly named this skill in their message.

    Matches patterns like:
      - "use the pdf skill"
      - "用pdf这个skill"
      - "/pdf"
      - "用pdf技能读取"

    Uses a combination of exact substring checks rather than word-boundary
    regex, because Python's \w includes CJK characters, making \b useless
    for Chinese text.
    """
    name = skill_name.lower()

    # Direct slash-command style: /pdf
    if f"/{name}" in msg_lower:
        return True

    # Does the skill name appear at all? Use ASCII-only boundaries since
    # Python \w includes Unicode, so we manually check[a-z] boundaries.
    if name not in msg_lower:
        return False

    # Verify skill name is not embedded in another ASCII word,
    # but CAN be adjacent to CJK characters.
    idx = msg_lower.find(name)
    if idx > 0 and msg_lower[idx - 1].isascii() and msg_lower[idx - 1].isalnum():
        return False
    end = idx + len(name)
    if end < len(msg_lower) and msg_lower[end].isascii() and msg_lower[end].isalnum():
        return False

    # Context indicators within 30 chars of the skill name
    context_words = ["skill", "技能", "use", "用", "使用", "调用", "插件", "skill"]
    window_start = max(0, idx - 30)
    window_end = min(len(msg_lower), end + 30)
    window = msg_lower[window_start:window_end]

    return any(cw in window for cw in context_words)

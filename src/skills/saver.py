"""Skill saver — saves learned capabilities as new skill directories with SKILL.md.

Follows the standard Claude Code skill format:
    skill-name/
    └── SKILL.md
"""

import os
from pathlib import Path


def save_skill(
    name: str,
    description: str,
    content: str,
    skills_dir: str = "./skills",
    version: str = "1.0",
    allowed_tools: str = "",
    disable_model_invocation: bool = False,
    **extra_fields,
) -> str:
    """Save a new skill as a directory with SKILL.md inside.

    Args:
        name: Unique skill name. Lowercase letters, digits, hyphens only.
        description: What the skill does. Include trigger phrases — this controls
                     whether the model auto-loads it.
        content: Markdown body with instructions, constraints, examples.
        skills_dir: Root skills directory.
        version: Semantic version string.
        allowed_tools: Space-separated tool list to pre-approve.
        disable_model_invocation: If True, model will never auto-load this skill.

    Returns:
        Path to the created SKILL.md file.
    """
    skills_dir = Path(skills_dir)
    safe_name = _sanitize_name(name)
    skill_dir = skills_dir / safe_name
    os.makedirs(skill_dir, exist_ok=True)

    # Build frontmatter
    fm_lines = [
        f"name: {safe_name}",
        f"description: {description}",
        f'version: "{version}"',
    ]
    if allowed_tools:
        fm_lines.append(f"allowed-tools: {allowed_tools}")
    if disable_model_invocation:
        fm_lines.append("disable-model-invocation: true")
    for key, value in extra_fields.items():
        if value:
            fm_lines.append(f"{key}: {value}")

    frontmatter = "\n".join(fm_lines)

    skill_md = f"""---
{frontmatter}
---

{content}
"""
    filepath = skill_dir / "SKILL.md"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(skill_md)

    return str(filepath)


def _sanitize_name(name: str) -> str:
    """Ensure the name follows skill naming rules: lowercase, hyphens only."""
    safe = name.lower().strip().replace(" ", "-").replace("_", "-")
    # Remove invalid characters
    safe = "".join(c for c in safe if c.islower() or c.isdigit() or c == "-")
    # Collapse consecutive hyphens
    while "--" in safe:
        safe = safe.replace("--", "-")
    # Strip leading/trailing hyphens
    safe = safe.strip("-")
    return safe or "unnamed-skill"

"""Skill loader — scans directories for SKILL.md with YAML frontmatter.

Standard Claude Code skill format:
    skill-name/              # folder name must match name in frontmatter
    ├── SKILL.md             # required: YAML frontmatter + markdown body
    ├── scripts/             # optional: executable code
    ├── references/          # optional: detailed docs loaded on-demand
    └── assets/              # optional: templates, images (never auto-loaded)
"""

import os
import re
import yaml
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    content: str
    dir_path: str = ""

    # Optional frontmatter fields
    version: str = ""
    license_info: str = ""
    compatibility: str = ""
    allowed_tools: str = ""
    argument_hint: str = ""
    user_invocable: bool = True
    disable_model_invocation: bool = False
    model: str = ""
    context: str = ""  # "fork" for isolated subagent
    agent: str = ""

    def __repr__(self):
        return f"Skill({self.name}: {self.description[:60]})"

    @property
    def should_auto_load(self) -> bool:
        """Whether the model can auto-load this skill based on description match."""
        return not self.disable_model_invocation and bool(self.description)


class SkillLoader:
    """Load and manage skills from directories containing SKILL.md files."""

    def __init__(self, skills_dir: str = "./skills"):
        self.skills_dir = Path(skills_dir)
        self._skills: dict[str, Skill] = {}

    def load_all(self) -> list[Skill]:
        """Scan skills_dir for <name>/SKILL.md and load all."""
        self._skills.clear()

        if not self.skills_dir.exists():
            os.makedirs(self.skills_dir, exist_ok=True)

        found = list(self.skills_dir.rglob("SKILL.md"))
        if not found:
            self._create_example_skill()

        for skill_md in self.skills_dir.rglob("SKILL.md"):
            try:
                skill = self._parse_skill_dir(skill_md)
                if skill:
                    self._skills[skill.name] = skill
            except Exception as e:
                print(f"[Skills] Failed to load {skill_md}: {e}")

        return list(self._skills.values())

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list_names(self) -> list[str]:
        return list(self._skills.keys())

    def list_all(self) -> list[Skill]:
        return list(self._skills.values())

    def _parse_skill_dir(self, skill_md_path: Path) -> Skill | None:
        """Parse a SKILL.md file and validate against its parent directory name."""
        with open(skill_md_path, "r", encoding="utf-8") as f:
            raw = f.read()

        frontmatter, body = self._split_frontmatter(raw)
        if frontmatter is None:
            print(f"[Skills] {skill_md_path} has no valid YAML frontmatter, skipping")
            return None

        folder_name = skill_md_path.parent.name
        name = frontmatter.get("name", "")

        if not name:
            print(f"[Skills] {skill_md_path} missing 'name' in frontmatter, skipping")
            return None

        if name != folder_name:
            print(f"[Skills] Warning: folder '{folder_name}' != name '{name}' in {skill_md_path}")

        return Skill(
            name=name,
            description=frontmatter.get("description", ""),
            content=body.strip(),
            dir_path=str(skill_md_path.parent),
            version=frontmatter.get("version", ""),
            license_info=frontmatter.get("license", ""),
            compatibility=frontmatter.get("compatibility", ""),
            allowed_tools=frontmatter.get("allowed-tools", ""),
            argument_hint=frontmatter.get("argument-hint", ""),
            user_invocable=frontmatter.get("user-invocable", True),
            disable_model_invocation=frontmatter.get("disable-model-invocation", False),
            model=frontmatter.get("model", ""),
            context=frontmatter.get("context", ""),
            agent=frontmatter.get("agent", ""),
        )

    def _split_frontmatter(self, raw: str) -> tuple[dict | None, str]:
        """Split YAML frontmatter from markdown body."""
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", raw, re.DOTALL)
        if not match:
            return None, raw

        try:
            frontmatter = yaml.safe_load(match.group(1))
        except yaml.YAMLError as e:
            print(f"[Skills] YAML parse error: {e}")
            return None, raw

        if not isinstance(frontmatter, dict):
            return None, raw

        body = raw[match.end():].strip()
        return frontmatter, body

    def _create_example_skill(self):
        """Create a template skill directory so the skills/ folder is not empty."""
        skill_dir = self.skills_dir / "example-skill"
        if skill_dir.exists():
            return

        os.makedirs(skill_dir, exist_ok=True)
        example = """---
name: example-skill
description: A template skill showing the standard format. Replace with your own skill.
version: "1.0"
---

# Example Skill

This is an example skill following the Claude Code skill format.

## When to Use
- When the user asks about X
- When working with Y

## Instructions
1. First, do A
2. Then, do B
3. Finally, report C

## Notes
- Replace this content with your own skill instructions
- Keep the body under 500 lines for optimal context usage
"""
        skill_md = skill_dir / "SKILL.md"
        with open(skill_md, "w", encoding="utf-8") as f:
            f.write(example)

        # Parse and register it
        skill = self._parse_skill_dir(skill_md)
        if skill:
            self._skills[skill.name] = skill

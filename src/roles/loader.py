"""Role loader — loads .md role files with YAML frontmatter.

Roles define session-level behavior injected at the top of the system prompt.
Format mirrors SKILL.md:
    ---
    name: research
    display_name: 调研助手
    description: 专注于信息调研
    icon: 🔍
    tools: web_search, file_write       # optional, comma-separated
    model: chat                         # optional, model route name
    ---

    # Role instructions (markdown body)
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml


class RoleError(Exception):
    """Raised when a role cannot be created or updated."""


@dataclass
class Role:
    name: str
    display_name: str
    description: str
    system_prompt: str       # markdown body (without frontmatter)
    icon: str = "🤖"
    tools_override: list[str] | None = None   # None = inherit default
    model: str | None = None                  # None = inherit default
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


def build_role_presence(role: "Role") -> str:
    """Build shared role expression guidance for prompts and UI events."""
    lines: list[str] = []
    if role.personality:
        lines.append(f"- Working style: {role.personality}")
    if role.tone:
        lines.append(f"- Tone: {role.tone}")
    if role.greeting:
        lines.append(f"- Opening tone: {role.greeting}")
    if role.signoff:
        lines.append(f"- Signoff tone: {role.signoff}")
    if role.handoff_style:
        lines.append(f"- Handoff style: {role.handoff_style}")
    if role.idle_style:
        lines.append(f"- Idle presence: {role.idle_style}")
    if role.busy_style:
        lines.append(f"- Busy presence: {role.busy_style}")
    if role.success_style:
        lines.append(f"- Success signal: {role.success_style}")
    if role.failure_style:
        lines.append(f"- Failure signal: {role.failure_style}")
    return "\n".join(lines)


class RoleLoader:
    """Load and manage roles from a directory of .md files."""

    def __init__(self, roles_dir: str = "./roles"):
        self.roles_dir = Path(roles_dir)
        self._roles: dict[str, Role] = {}

    def load_all(self) -> list[Role]:
        """Scan roles_dir for *.md and load all."""
        self._roles.clear()

        if not self.roles_dir.exists():
            return []

        for role_md in sorted(self.roles_dir.glob("*.md")):
            try:
                role = self._parse_role_file(role_md)
                if role:
                    self._roles[role.name] = role
            except Exception as e:
                print(f"[Roles] Failed to load {role_md}: {e}")

        return list(self._roles.values())

    def get(self, name: str) -> Role | None:
        return self._roles.get(name)

    def list_roles(self) -> list[Role]:
        return list(self._roles.values())

    def _parse_role_file(self, role_md: Path) -> Role | None:
        with open(role_md, "r", encoding="utf-8") as f:
            raw = f.read()

        frontmatter, body = self._split_frontmatter(raw)
        if frontmatter is None:
            print(f"[Roles] {role_md} has no valid YAML frontmatter, skipping")
            return None

        name = frontmatter.get("name", "")
        display_name = frontmatter.get("display_name", "")
        description = frontmatter.get("description", "")

        if not name:
            print(f"[Roles] {role_md} missing 'name' in frontmatter, skipping")
            return None

        # Parse optional tools (comma-separated string → list)
        tools_raw = frontmatter.get("tools", "")
        tools_override = None
        if tools_raw:
            tools_override = [t.strip() for t in tools_raw.split(",") if t.strip()]

        return Role(
            name=name,
            display_name=display_name,
            description=description,
            icon=frontmatter.get("icon", "🤖"),
            system_prompt=body.strip(),
            tools_override=tools_override,
            model=frontmatter.get("model", None),
            personality=frontmatter.get("personality", ""),
            greeting=frontmatter.get("greeting", ""),
            signoff=frontmatter.get("signoff", ""),
            status_text=frontmatter.get("status_text", ""),
            tone=frontmatter.get("tone", ""),
            idle_style=frontmatter.get("idle_style", ""),
            busy_style=frontmatter.get("busy_style", ""),
            success_style=frontmatter.get("success_style", ""),
            failure_style=frontmatter.get("failure_style", ""),
            handoff_style=frontmatter.get("handoff_style", ""),
        )

    @staticmethod
    def _split_frontmatter(raw: str) -> tuple[dict | None, str]:
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", raw, re.DOTALL)
        if not match:
            return None, raw

        try:
            frontmatter = yaml.safe_load(match.group(1))
        except yaml.YAMLError as e:
            print(f"[Roles] YAML parse error: {e}")
            return None, raw

        if not isinstance(frontmatter, dict):
            return None, raw

        body = raw[match.end():].strip()
        return frontmatter, body

    def save_role(self, name: str, display_name: str, description: str,
                  system_prompt: str, icon: str = "🤖",
                  tools_override: list[str] | None = None,
                  model: str | None = None,
                  personality: str = "",
                  greeting: str = "",
                  signoff: str = "",
                  status_text: str = "",
                  tone: str = "",
                  idle_style: str = "",
                  busy_style: str = "",
                  success_style: str = "",
                  failure_style: str = "",
                  handoff_style: str = "") -> Role:
        """Create or update a role. Writes to roles/{name}.md.

        Uses round-trip YAML parsing to preserve existing fields and avoid
        data loss from missing if-else branches.
        """
        self._validate_name(name)

        file_path = self.roles_dir / f"{name}.md"
        persona_fields = {
            "personality": personality,
            "greeting": greeting,
            "signoff": signoff,
            "status_text": status_text,
            "tone": tone,
            "idle_style": idle_style,
            "busy_style": busy_style,
            "success_style": success_style,
            "failure_style": failure_style,
            "handoff_style": handoff_style,
        }

        if file_path.exists():
            # Round-trip: read existing file, update frontmatter
            raw = file_path.read_text(encoding="utf-8")
            frontmatter, body = self._split_frontmatter(raw)
            if frontmatter is None:
                frontmatter = {}
            if not body:
                body = system_prompt.strip()
        else:
            frontmatter = {}
            body = system_prompt.strip()

        frontmatter.update({
            "name": name,
            "display_name": display_name,
            "description": description,
            "icon": icon,
        })
        if tools_override:
            frontmatter["tools"] = ", ".join(tools_override)
        if model:
            frontmatter["model"] = model
        for key, value in persona_fields.items():
            if value:
                frontmatter[key] = value

        content = "---\n"
        content += yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True,
                             sort_keys=False, width=120)
        content += "---\n\n"
        content += body + "\n"

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

        # Update in-memory cache
        role = Role(
            name=name,
            display_name=display_name,
            description=description,
            icon=icon,
            system_prompt=body,
            tools_override=tools_override,
            model=model,
            personality=personality,
            greeting=greeting,
            signoff=signoff,
            status_text=status_text,
            tone=tone,
            idle_style=idle_style,
            busy_style=busy_style,
            success_style=success_style,
            failure_style=failure_style,
            handoff_style=handoff_style,
        )
        self._roles[name] = role
        return role

    def delete_role(self, name: str) -> bool:
        """Delete a role file and remove from cache.

        Returns False if the role doesn't exist.
        Raises RoleError if trying to delete the default role.
        """
        if name in ("executor", "task_agent"):
            raise RoleError("Cannot delete built-in roles")

        file_path = self.roles_dir / f"{name}.md"
        if not file_path.exists():
            return False

        file_path.unlink()
        self._roles.pop(name, None)
        return True

    @staticmethod
    def _validate_name(name: str):
        """Check that a role name is filesystem-safe."""
        if not name or not name.strip():
            raise RoleError("Role name cannot be empty")
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', name):
            raise RoleError(
                "Role name must contain only letters, numbers, underscores, or hyphens")

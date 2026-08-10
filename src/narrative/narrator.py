"""Narrator — converts StructuredSummary + role templates into hallway narratives."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from src.narrative.event_classifier import StructuredSummary

TEMPLATES_DIR = Path(__file__).parent / "templates"
FALLBACK_TEMPLATES = {
    "start": "{actor}开始处理「{task}」了。",
    "complete": "{actor}完成了「{task}」。",
    "fail": "{actor}在「{task}」上遇到了问题。",
    "create": "新任务「{task}」已创建。",
    "cancel": "任务「{task}」已取消。",
    "handoff": "{actor}把「{task}」的结果交给了{next_actor}。",
    "default": "{actor}执行了{action}（{task}）。",
}


def _load_template_yaml(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return {}
    return {k: str(v) for k, v in data.items()}


class Narrator:
    """Generates natural-language hallway narratives from structured summaries.

    Usage:
        narrator = Narrator()
        narrator.load_templates("/path/to/templates")  # optional, defaults to src/narrative/templates/
        text = narrator.narrate(summary, role)
    """

    def __init__(self, templates_dir: str | Path | None = None):
        self.templates_dir = Path(templates_dir) if templates_dir else TEMPLATES_DIR
        self._role_templates: dict[str, dict[str, str]] = {}
        self._load_all()

    def _load_all(self) -> None:
        if not self.templates_dir.exists():
            return
        for yaml_file in self.templates_dir.glob("*.yaml"):
            role_name = yaml_file.stem
            self._role_templates[role_name] = _load_template_yaml(yaml_file)

    def load_templates(self, templates_dir: str | Path) -> None:
        self.templates_dir = Path(templates_dir)
        self._role_templates.clear()
        self._load_all()

    def narrate(self, summary: StructuredSummary, role: Any | None = None) -> str:
        """Generate a hallway narrative for the given summary.

        Args:
            summary: The StructuredSummary from EventClassifier.
            role: Optional Role object for accessing handoff_style and name.

        Returns:
            A natural-language string describing the event.
        """
        templates = self._role_templates.get(summary.actor_role, {})
        template = templates.get(summary.action)

        if not template:
            template = FALLBACK_TEMPLATES.get(summary.action, FALLBACK_TEMPLATES["default"])

        return self._render(template, summary)

    def narrate_all(self, summaries: list[StructuredSummary]) -> list[str]:
        return [self.narrate(s) for s in summaries]

    @staticmethod
    def _render(template: str, summary: StructuredSummary) -> str:
        ctx: dict[str, str] = {
            "actor": summary.actor or "某人",
            "action": summary.action,
            "task": summary.task or "某项工作",
            "next_actor": summary.next_actor or "同事",
            "urgency": summary.urgency,
            "quality": summary.quality,
            "error": summary.error,
            "actor_role": summary.actor_role,
        }
        try:
            return template.format(**ctx)
        except KeyError:
            return FALLBACK_TEMPLATES["default"].format(**ctx)

"""MemoryManager — file-based layered memory system.

Manages four layers under a configurable directory (default: ./memory):
  - execution_log.jsonl: Append-only log of managed task results (no LLM)
  - patterns.md: SOPs distilled from execution_log (cross-day, LLM)
  - user_prefs.md: User-maintained preferences (no LLM, manual edits)
  - today.md: Interactive session summaries (appended on each close)

Memory injection is session-type-aware:
  - interactive: user_prefs + today
  - managed: patterns + execution_log (last 20)

Zero external dependencies — pure Markdown + JSON files.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

# Memory three-layer separation:
# - identity: Core role identity, immutable by evolution (read-only from role files)
# - workflow: SOPs and workflows, distilled from execution_log (evolvable)
# - voice: User interaction preferences, distilled from sessions (evolvable)
MEMORY_LAYERS = {
    "identity": "角色核心身份，任何进化不可覆盖",
    "workflow": "工作流程与SOP",
    "voice": "语气与表达偏好",
}

PROJECT_DIR = "project"
USER_DIR = "user"
TASK_EXPERIENCE_DIR = "task_experience"
ROLE_EXPERIENCE_DIR = "role_experience"
EVENTS_DIR = "events"
TODAY_FILE = "today.md"
PROJECT_MEMORY_FILE = "project.md"
USER_PROFILE_FILE = "profile.md"
EVENT_LOG_FILE = "events.jsonl"
LONGTERM_FILE = PROJECT_MEMORY_FILE
SUMMARIES_DIR = "summaries"
EXECUTION_LOG_FILE = "execution_log.jsonl"
PATTERNS_FILE = "patterns.md"
USER_PREFS_FILE = "user_prefs.md"
SUPERVISOR_DIR = "supervisor"
TASK_AGENT_DIR = "task_agent"
ROLES_DIR = "roles"
DAILY_LOG_FILE = "daily_log.md"
INSIGHTS_FILE = "insights.md"
ACTION_ITEMS_FILE = "action_items.md"
ROLE_DISPATCH_FILE = "role_dispatch.md"

USER_PREFS_TEMPLATE = """\
# 用户偏好配置
# 直接编辑此文件，重启服务后生效
# 也可以在 Chat 里说"帮我更新 user_prefs.md"

- 日报时间: 18:00
- 报告格式: 简洁 Markdown，不超 500 字
- 失败处理: 自动重试 2 次，仍失败则通知我
"""


class MemoryManager:
    """Manages agent memory using local Markdown / JSONL files.

    Usage:
        memory = MemoryManager(base_dir="./memory")
        memory.append_execution_log(...)
        memory.check_and_distill_patterns()
        prompt_section = memory.assemble_memory(session_type="managed")
    """

    def __init__(self, agent_name: str = "workpartner",
                 model: "ChatOpenAI | None" = None,
                 base_dir: "str | Path | None" = None):
        self._agent_name = agent_name
        self._model = model
        self._base_dir = base_dir
        self._memory_dir = self._init_memory_dir()

    def _init_memory_dir(self) -> Path:
        """Create memory directory structure and seed template files."""
        if self._base_dir is not None:
            base = Path(self._base_dir)
        else:
            base = Path.home() / ".workpartner" / "agents" / self._agent_name / "memory"
        base.mkdir(parents=True, exist_ok=True)
        (base / PROJECT_DIR).mkdir(parents=True, exist_ok=True)
        (base / USER_DIR).mkdir(parents=True, exist_ok=True)
        (base / TASK_EXPERIENCE_DIR).mkdir(parents=True, exist_ok=True)
        (base / ROLE_EXPERIENCE_DIR).mkdir(parents=True, exist_ok=True)
        (base / EVENTS_DIR).mkdir(parents=True, exist_ok=True)
        (base / SUMMARIES_DIR).mkdir(parents=True, exist_ok=True)
        (base / SUPERVISOR_DIR).mkdir(parents=True, exist_ok=True)
        (base / TASK_AGENT_DIR).mkdir(parents=True, exist_ok=True)
        (base / ROLES_DIR).mkdir(parents=True, exist_ok=True)

        # Seed execution_log.jsonl (empty, append-only)
        log_path = base / TASK_EXPERIENCE_DIR / EXECUTION_LOG_FILE
        if not log_path.exists():
            log_path.touch()

        # Seed user_prefs.md with commented template
        prefs_path = base / USER_DIR / USER_PROFILE_FILE
        if not prefs_path.exists():
            prefs_path.write_text(USER_PREFS_TEMPLATE, encoding="utf-8")

        return base

    # -- Execution log --

    def append_execution_log(
        self,
        task_id: str,
        title: str,
        result: str,
        duration_sec: float,
        tools: list[str],
        error: str | None = None,
        result_summary: str | None = None,
        role: str | None = None,
        thread_id: str | None = None,
    ) -> None:
        """Synchronously append one task result to execution_log.jsonl."""
        record = {
            "task_id": task_id,
            "title": title,
            "role": role,
            "thread_id": thread_id,
            "result": result,
            "duration_sec": round(duration_sec, 1),
            "tools": tools,
            "result_summary": result_summary,
            "error": error,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        log_path = self._memory_dir / TASK_EXPERIENCE_DIR / EXECUTION_LOG_FILE
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.debug("MemoryManager: execution_log appended [%s] %s=%s", task_id, title, result)

    def append_task_agent_log(
        self,
        task_id: str,
        title: str,
        role: str,
        strategy: str,
        result: str,
        tools: list[str] | None = None,
        result_summary: str | None = None,
        error: str | None = None,
    ) -> None:
        """Append task-agent execution strategy/history."""
        record = {
            "task_id": task_id,
            "title": title,
            "role": role,
            "strategy": strategy,
            "result": result,
            "tools": tools or [],
            "result_summary": result_summary,
            "error": error,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self._append_jsonl(self._memory_dir / TASK_EXPERIENCE_DIR / EXECUTION_LOG_FILE, record)

    def append_role_log(
        self,
        role: str,
        task_id: str,
        title: str,
        result: str,
        tools: list[str] | None = None,
        result_summary: str | None = None,
        error: str | None = None,
    ) -> None:
        """Append professional experience for one role."""
        role_key = self._safe_role_name(role or "default")
        record = {
            "task_id": task_id,
            "title": title,
            "result": result,
            "tools": tools or [],
            "result_summary": result_summary,
            "error": error,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self._append_jsonl(self._memory_dir / ROLE_EXPERIENCE_DIR / f"{role_key}.jsonl", record)

    def append_supervisor_log(
        self,
        event: str,
        title: str,
        detail: str,
        task_id: str | None = None,
        level: str = "info",
    ) -> None:
        """Append a global supervisor observation to daily_log.md."""
        path = self._memory_dir / SUPERVISOR_DIR / DAILY_LOG_FILE
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ts = datetime.now(timezone.utc).isoformat()
        line = f"- {date_str} [{level}] {event}: {title}"
        if task_id:
            line += f" ({task_id})"
        if detail:
            line += f" — {detail}"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def add_supervisor_action_item(
        self,
        text: str,
        task_id: str | None = None,
        level: str = "info",
    ) -> None:
        """Append a follow-up action item for the supervisor board."""
        path = self._memory_dir / SUPERVISOR_DIR / ACTION_ITEMS_FILE
        ts = datetime.now(timezone.utc).isoformat()
        item = {"ts": ts, "level": level, "task_id": task_id, "text": text}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def read_supervisor_action_items(self, limit: int = 20) -> list[dict]:
        path = self._memory_dir / SUPERVISOR_DIR / ACTION_ITEMS_FILE
        return self._read_jsonl(path, limit=limit)

    def remove_action_items_for_task_id(self, task_id: str) -> int:
        """Remove all action items matching the given task_id.

        Returns the number of items removed.
        """
        path = self._memory_dir / SUPERVISOR_DIR / ACTION_ITEMS_FILE
        if not path.exists():
            return 0
        records: list[dict] = []
        removed = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if record.get("task_id") == task_id:
                    removed += 1
                    continue
                records.append(record)
            except json.JSONDecodeError:
                continue
        if removed:
            path.write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"
                if records else "",
                encoding="utf-8",
            )
        return removed

    def append_event_log(self, event: Any) -> None:
        """Append a canonical AgentEvent to the audit-only event stream.

        This log is useful for UI replay and debugging, but it is not injected
        into prompts as long-term memory.
        """
        if hasattr(event, "model_dump"):
            record = event.model_dump()
        elif isinstance(event, dict):
            record = dict(event)
        else:
            record = {"event": str(event), "ts": datetime.now(timezone.utc).isoformat()}
        self._append_jsonl(self._memory_dir / EVENTS_DIR / EVENT_LOG_FILE, record)

    def append_role_dispatch(
        self,
        role: str,
        task_type: str,
        tools_chain: str,
        date_str: str | None = None,
    ) -> None:
        """Append a role dispatch lesson to task_experience/role_dispatch.md."""
        date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        line = f"- {date_str}: [{role}] 适合 [{task_type}]，推荐工具链：{tools_chain}\n"
        path = self._memory_dir / TASK_EXPERIENCE_DIR / ROLE_DISPATCH_FILE
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)

    def read_role_dispatch(self, limit: int = 12) -> list[dict[str, str]]:
        """Read recent role dispatch lessons from role_dispatch.md."""
        path = self._memory_dir / TASK_EXPERIENCE_DIR / ROLE_DISPATCH_FILE
        if not path.exists():
            return []

        records: list[dict[str, str]] = []
        pattern = re.compile(
            r"^- (?P<date>\d{4}-\d{2}-\d{2}): \[(?P<role>[^\]]+)\] "
            r"适合 \[(?P<task_type>[^\]]+)\]，推荐工具链：(?P<tools_chain>.+)$"
        )
        for line in path.read_text(encoding="utf-8").splitlines():
            match = pattern.match(line.strip())
            if match:
                records.append(match.groupdict())
        return records[-limit:]

    def summarize_role_health(self, limit: int = 20) -> list[dict[str, Any]]:
        """Summarize recent role outcomes for supervisor-facing guidance."""
        result: list[dict[str, Any]] = []
        for role_file in sorted((self._memory_dir / ROLE_EXPERIENCE_DIR).glob("*.jsonl")):
            records = self._read_jsonl(role_file, limit=limit)
            if not records:
                continue
            total = len(records)
            success = sum(1 for record in records if record.get("result") == "done")
            latest = records[-1]
            result.append({
                "role": role_file.stem,
                "recent_total": total,
                "recent_success": success,
                "success_rate": round(success / total, 2) if total else 0.0,
                "latest_result": latest.get("result", ""),
                "latest_title": latest.get("title", ""),
                "latest_summary": latest.get("result_summary") or latest.get("error") or "",
            })
        return result

    def assemble_role_memory(self, role_name: str, limit: int = 5) -> str:
        """Assemble recent professional memory for one role."""
        role_key = self._safe_role_name(role_name or "default")
        records = self._read_jsonl(self._memory_dir / ROLE_EXPERIENCE_DIR / f"{role_key}.jsonl", limit=limit)
        if not records:
            records = self._read_jsonl(self._memory_dir / ROLES_DIR / f"{role_key}.jsonl", limit=limit)
        if not records:
            return ""
        lines = [json.dumps(record, ensure_ascii=False) for record in records]
        return "<role_memory>\n" + "\n".join(lines) + "\n</role_memory>"

    def assemble_supervisor_memory(self) -> str:
        """Assemble global memory for the supervisor."""
        parts: list[str] = []

        # daily_log: filter by last 7 days, fallback to char truncation if format incompatible
        daily_path = self._memory_dir / SUPERVISOR_DIR / DAILY_LOG_FILE
        if daily_path.exists():
            content = daily_path.read_text(encoding="utf-8").strip()
            if content:
                cutoff_date = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()
                date_re = re.compile(r"^- (\d{4}-\d{2}-\d{2})\s")
                filtered_lines = []
                all_dated = True
                for line in content.splitlines():
                    m = date_re.match(line)
                    if m:
                        if m.group(1) >= cutoff_date:
                            filtered_lines.append(line)
                    else:
                        all_dated = False
                if all_dated:
                    daily_content = "\n".join(filtered_lines)
                else:
                    daily_content = content[-4000:]
                if daily_content:
                    parts.append(f"<daily_log>\n{daily_content}\n</daily_log>")

        for filename, tag, max_chars in [
            (INSIGHTS_FILE, "insights", 2000),
            (ACTION_ITEMS_FILE, "action_items", 3000),
        ]:
            path = self._memory_dir / SUPERVISOR_DIR / filename
            if path.exists():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(f"<{tag}>\n{content[-max_chars:]}\n</{tag}>")
        prefs_path = self._memory_dir / USER_DIR / USER_PROFILE_FILE
        if not prefs_path.exists():
            prefs_path = self._memory_dir / USER_PREFS_FILE
        if prefs_path.exists():
            prefs = prefs_path.read_text(encoding="utf-8").strip()
            if prefs:
                parts.append(f"<user_prefs>\n{prefs[-2000:]}\n</user_prefs>")
        if not parts:
            return ""
        return "<memory>\n\n" + "\n\n".join(parts) + "\n\n</memory>"

    def _append_jsonl(self, path: Path, record: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def _read_jsonl(path: Path, limit: int = 20) -> list[dict]:
        if not path.exists():
            return []
        records: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records[-limit:]

    @staticmethod
    def _safe_role_name(role: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_-]+", "_", role).strip("_") or "default"

    # -- Patterns distillation --

    async def distill_patterns(self) -> str:
        """Read all execution_log.jsonl, distill SOPs, overwrite patterns.md."""
        log_path = self._memory_dir / TASK_EXPERIENCE_DIR / EXECUTION_LOG_FILE
        if not log_path.exists():
            return ""
        raw = log_path.read_text(encoding="utf-8").strip()
        if not raw:
            return ""

        records: list[dict] = []
        for line in raw.splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if not records:
            return ""

        if self._model is not None:
            patterns = await self._llm_distill_patterns(records)
        else:
            patterns = self._fallback_distill_patterns(records)

        patterns_path = self._memory_dir / TASK_EXPERIENCE_DIR / PATTERNS_FILE
        patterns_path.write_text(patterns, encoding="utf-8")
        logger.info("MemoryManager: patterns.md distilled from %d records", len(records))
        return patterns

    async def _llm_distill_patterns(self, records: list[dict]) -> str:
        from langchain_core.messages import HumanMessage

        formatted = json.dumps(records, ensure_ascii=False, indent=2)
        prompt = (
            "以下是 Agent 执行任务的历史记录（JSON 格式）。\n"
            "请提炼成操作模式（SOP），按任务类型分组，每组格式：\n\n"
            "## 任务类型名称\n"
            "- 工具链: tool1 → tool2\n"
            "- 成功率: X% (N/M)\n"
            "- 常见失败: 原因（解决方法）\n"
            "- 策略摘要: 简要说明成功策略\n\n"
            "只保留有实际价值的模式，过滤噪音。\n\n"
            f"<execution_log>\n{formatted[:10000]}\n</execution_log>"
        )
        try:
            result = await self._model.ainvoke([HumanMessage(content=prompt)])
            return result.content or ""
        except Exception:
            logger.warning("MemoryManager: LLM distill_patterns failed, using fallback")
            return self._fallback_distill_patterns(records)

    @staticmethod
    def _fallback_distill_patterns(records: list[dict]) -> str:
        lines = ["# 操作模式（自动提炼）\n"]
        for r in records[-20:]:
            tools_str = ", ".join(r.get("tools") or []) or "-"
            lines.append(
                f"- [{r.get('ts', '')[:10]}] {r.get('title', '')} "
                f"→ {r.get('result', '')} ({tools_str})"
            )
        return "\n".join(lines)

    async def distill_insights(self) -> str:
        """Read 7 days of supervisor/daily_log.md and distill cross-task insights.

        Writes result to supervisor/insights.md (overwrite). If LLM fails,
        the existing file is preserved unchanged.
        """
        daily_path = self._memory_dir / SUPERVISOR_DIR / DAILY_LOG_FILE
        if not daily_path.exists():
            return ""
        daily_content = daily_path.read_text(encoding="utf-8").strip()
        if not daily_content:
            return ""

        # Filter to last 7 days
        cutoff = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()
        import re as _re
        date_re = _re.compile(r"^- (\d{4}-\d{2}-\d{2})\s")
        filtered = []
        for line in daily_content.splitlines():
            m = date_re.match(line)
            if m and m.group(1) < cutoff:
                continue
            filtered.append(line)
        if not filtered:
            return ""
        recent_log = "\n".join(filtered)

        # Pass existing insights as context so the new version can include old ones
        insights_path = self._memory_dir / SUPERVISOR_DIR / INSIGHTS_FILE
        old_insights = ""
        if insights_path.exists():
            old_insights = insights_path.read_text(encoding="utf-8").strip()

        if self._model is None:
            return ""

        from langchain_core.messages import HumanMessage
        prompt = (
            "以下是大管家近 7 天的执行日志（每行一条事件记录），以及之前积累的洞察。\n"
            "请提炼出：\n"
            "1. 用户最常交代的任务类型\n"
            "2. 执行质量趋势（成功率、常见失败原因）\n"
            "3. 值得关注的规律或用户偏好\n\n"
            "用简洁的 Markdown 格式输出，每类洞察不超过 3 条。\n\n"
            f"<daily_log>\n{recent_log[-6000:]}\n</daily_log>\n\n"
            + (f"<previous_insights>\n{old_insights[-2000:]}\n</previous_insights>" if old_insights else "")
        )
        try:
            result = await self._model.ainvoke([HumanMessage(content=prompt)])
            insights = result.content or ""
        except Exception:
            logger.warning("MemoryManager: distill_insights LLM call failed, keeping existing file")
            return ""

        if insights:
            insights_path.write_text(insights, encoding="utf-8")
            logger.info("MemoryManager: insights.md updated (%d chars)", len(insights))
        return insights

    def check_and_distill_patterns(self) -> bool:
        """Trigger distill_patterns() if execution_log was last modified before today.

        Returns True if distillation was triggered.
        """
        log_path = self._memory_dir / TASK_EXPERIENCE_DIR / EXECUTION_LOG_FILE
        if not log_path.exists() or log_path.stat().st_size == 0:
            return False

        mtime = datetime.fromtimestamp(log_path.stat().st_mtime, tz=timezone.utc)
        today = datetime.now(timezone.utc).date()

        if mtime.date() < today:
            logger.info("MemoryManager: cross-day detected, distilling patterns")
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self.distill_patterns())
                else:
                    loop.run_until_complete(self.distill_patterns())
            except RuntimeError:
                asyncio.run(self.distill_patterns())
            return True

        return False

    # -- Session summarization (interactive sessions) --

    async def summarize_session(self, messages: list[Any]) -> str:
        """Summarize a completed session and append to today.md.

        Args:
            messages: List of LangChain message objects from the session.

        Returns:
            Summary text that was written.
        """
        summary = self._generate_summary(messages)

        # Write raw summary to summaries/
        summary_path = (
            self._memory_dir / SUMMARIES_DIR
            / f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        )
        summary_path.write_text(
            json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message_count": len(messages),
                "summary": summary,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Append to today.md
        today_path = self._memory_dir / PROJECT_DIR / TODAY_FILE
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        with open(today_path, "a", encoding="utf-8") as f:
            f.write(f"\n## {date_str}\n\n{summary}\n")

        logger.info("MemoryManager: session summarized -> %s", summary_path.name)
        return summary

    def _generate_summary(self, messages: list[Any]) -> str:
        if self._model is not None:
            return self._llm_summarize(messages)
        return self._fallback_summarize(messages)

    def _llm_summarize(self, messages: list[Any]) -> str:
        from langchain_core.messages import HumanMessage

        formatted = "\n\n".join(
            f"[{getattr(m, 'type', '?')}] {getattr(m, 'content', '')}"
            for m in messages if getattr(m, "content", "")
        )

        prompt = (
            "Summarize this conversation session. Extract key decisions, "
            "facts, preferences, and pending tasks. Be dense but complete.\n\n"
            f"<session>\n{formatted[:8000]}\n</session>"
        )

        try:
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                self._model.ainvoke([HumanMessage(content=prompt)])
            )
            return result.content or ""
        except Exception:
            logger.warning("MemoryManager: LLM summarization failed, using fallback")
            return self._fallback_summarize(messages)

    @staticmethod
    def _fallback_summarize(messages: list[Any]) -> str:
        lines = []
        for m in messages:
            content = getattr(m, "content", "")
            role = getattr(m, "type", "?")
            if content and role in ("human", "ai"):
                short = str(content).replace("\n", " ")[:200]
                lines.append(f"[{role}] {short}")
        return "\n".join(lines[:10]) if lines else "(empty session)"

    # -- Long-term memory compilation (interactive sessions) --

    async def compile_longterm(self) -> str:
        """Extract persistent facts from today.md into longterm.md."""
        today_path = self._memory_dir / PROJECT_DIR / TODAY_FILE
        if not today_path.exists():
            return ""

        today_content = today_path.read_text(encoding="utf-8")
        if not today_content.strip():
            return ""

        if self._model is not None:
            content = await self._llm_compile_longterm(today_content)
        else:
            content = (
                f"# Long-term Memory\n\n"
                f"> Extracted from today.md on {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
                f"{today_content}"
            )

        longterm_path = self._memory_dir / PROJECT_DIR / PROJECT_MEMORY_FILE
        longterm_path.write_text(content, encoding="utf-8")
        logger.info("MemoryManager: longterm.md compiled")
        return content

    async def _llm_compile_longterm(self, today_content: str) -> str:
        from langchain_core.messages import HumanMessage

        prompt = (
            "Review these daily session summaries. Extract ONLY persistent facts, "
            "user preferences, important patterns, and ongoing project context. "
            "Discard transient details. Format as a clean Markdown document.\n\n"
            f"<daily_summaries>\n{today_content[:10000]}\n</daily_summaries>"
        )

        try:
            result = await self._model.ainvoke([HumanMessage(content=prompt)])
            content = result.content or ""
        except Exception:
            logger.warning("MemoryManager: longterm compilation failed, using raw today.md")
            content = (
                f"# Long-term Memory\n\n"
                f"> Auto-extracted on {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
                f"{today_content}"
            )

        return content

    def check_and_compile_longterm(self) -> bool:
        """Trigger compile_longterm() if today.md is from a previous date."""
        today_path = self._memory_dir / PROJECT_DIR / TODAY_FILE
        if not today_path.exists():
            return False

        mtime = datetime.fromtimestamp(today_path.stat().st_mtime, tz=timezone.utc)
        today = datetime.now(timezone.utc).date()

        if mtime.date() < today:
            logger.info("MemoryManager: cross-day detected, compiling longterm")
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self.compile_longterm())
                else:
                    loop.run_until_complete(self.compile_longterm())
            except RuntimeError:
                asyncio.run(self.compile_longterm())
            return True

        return False

    # -- Memory assembly for system prompt --

    @staticmethod
    def _build_identity_layer(role: Any) -> str:
        """Generate an identity paragraph from a Role's frontmatter fields.

        Returns a short, LLM-readable identity definition marked [PROTECTED].
        """
        if role is None:
            return ""
        name = getattr(role, "name", "")
        display_name = getattr(role, "display_name", "")
        description = getattr(role, "description", "")
        personality = getattr(role, "personality", "")
        tone = getattr(role, "tone", "")

        parts = [f"[PROTECTED] Identity: {display_name} ({name})"]
        if description:
            parts.append(description)
        if personality:
            parts.append(f"Personality: {personality}")
        if tone:
            parts.append(f"Tone: {tone}")
        return "\n".join(parts)

    def assemble_memory(self, session_type: str = "interactive",
                        role: Any = None) -> str:
        """Assemble memory layers into a system prompt section.

        Args:
            session_type: "interactive" → user_prefs + today;
                          "managed"     → patterns + execution_log (last 20).
            role: Optional Role instance for identity layer injection.

        Returns:
            Markdown string for injection into system prompt, or "" if empty.
        """
        parts: list[str] = []

        # Identity layer: always first, marked [PROTECTED]
        identity = self._build_identity_layer(role)
        if identity:
            parts.append(identity)

        if session_type == "interactive":
            prefs_path = self._memory_dir / USER_DIR / USER_PROFILE_FILE
            if prefs_path.exists():
                content = prefs_path.read_text(encoding="utf-8").strip()
                meaningful = [
                    line for line in content.splitlines()
                    if line.strip() and not line.strip().startswith("#")
                ]
                if meaningful:
                    parts.append("<user_profile>\n" + "\n".join(meaningful) + "\n</user_profile>")

            project_path = self._memory_dir / PROJECT_DIR / PROJECT_MEMORY_FILE
            if project_path.exists():
                content = project_path.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(f"<project_memory>\n{content[-3000:]}\n</project_memory>")

            today_path = self._memory_dir / PROJECT_DIR / TODAY_FILE
            if today_path.exists():
                content = today_path.read_text(encoding="utf-8").strip()
                if content:
                    if len(content) > 2000:
                        content = content[-2000:]
                    parts.append(f"<today_memory>\n{content}\n</today_memory>")

        elif session_type in {"managed", "task_agent"}:
            task_patterns_path = self._memory_dir / TASK_EXPERIENCE_DIR / PATTERNS_FILE
            if task_patterns_path.exists():
                content = task_patterns_path.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(f"<task_agent_patterns>\n{content}\n</task_agent_patterns>")

            role_dispatch_path = self._memory_dir / TASK_EXPERIENCE_DIR / ROLE_DISPATCH_FILE
            if role_dispatch_path.exists():
                content = role_dispatch_path.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(f"<role_dispatch>\n{content}\n</role_dispatch>")

            task_log_path = self._memory_dir / TASK_EXPERIENCE_DIR / EXECUTION_LOG_FILE
            if task_log_path.exists():
                lines = task_log_path.read_text(encoding="utf-8").strip().splitlines()
                recent = lines[-10:]
                if recent:
                    parts.append(
                        "<task_agent_execution_recent>\n"
                        + "\n".join(recent)
                        + "\n</task_agent_execution_recent>"
                    )

            patterns_path = self._memory_dir / TASK_EXPERIENCE_DIR / PATTERNS_FILE
            if patterns_path.exists():
                content = patterns_path.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(f"<patterns>\n{content}\n</patterns>")

            log_path = self._memory_dir / TASK_EXPERIENCE_DIR / EXECUTION_LOG_FILE
            if log_path.exists():
                lines = log_path.read_text(encoding="utf-8").strip().splitlines()
                recent = lines[-20:]
                if recent:
                    parts.append(
                        "<execution_log_recent>\n"
                        + "\n".join(recent)
                        + "\n</execution_log_recent>"
                    )

        elif session_type == "supervisor":
            supervisor_memory = self.assemble_supervisor_memory()
            if supervisor_memory:
                return supervisor_memory

        if not parts:
            return ""

        return "<memory>\n\n" + "\n\n".join(parts) + "\n\n</memory>"

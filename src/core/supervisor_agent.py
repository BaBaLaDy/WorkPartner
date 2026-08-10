"""SupervisorAgent — event-driven global observer for WorkPartner.

The supervisor is intentionally lightweight: it subscribes to EventBus events,
writes global observations, performs cheap quality heuristics, and exposes
daily reports/status for the UI. It sleeps when no events arrive.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from src.hub.event_bus import EventBus
from src.hub.events import AgentEvent
from src.memory import TASK_EXPERIENCE_DIR, EXECUTION_LOG_FILE
from src.core.pin_summarizer import generate_pin_summary

logger = logging.getLogger(__name__)


class SupervisorAgent:
    """Global observer that sits above managed task sessions."""

    def __init__(self, engine: Any):
        self.engine = engine
        self.event_bus: EventBus = engine.event_bus
        self.memory = engine.memory
        self.thread_id = engine.session_manager.create_session(
            name="supervisor",
            session_type="supervisor",
            owner="system",
        )
        self._quality: dict[str, dict] = {}
        # Task 5: daily done counter for event-triggered reports
        self._daily_done_count = 0
        self._daily_date = datetime.now(timezone.utc).date().isoformat()
        self._subscribe()

    def _subscribe(self) -> None:
        self.event_bus.subscribe(EventBus.TASK_DONE, self._on_task_done)
        self.event_bus.subscribe(EventBus.TASK_FAILED, self._on_task_failed)
        self.event_bus.subscribe(EventBus.TASK_RETRYING, self._on_task_retrying)
        self.event_bus.subscribe(EventBus.TASK_ADDED, self._on_task_added)
        self.event_bus.subscribe(EventBus.ROLE_STARTED, self._on_role_started)
        self.event_bus.subscribe(EventBus.ROLE_DONE, self._on_role_done)
        self.event_bus.subscribe(EventBus.ROLE_FAILED, self._on_role_failed)

    async def _on_task_done(self, event: AgentEvent) -> None:
        data = event.payload
        task_id = data.get("task_id", "")
        thread_id = data.get("session_thread_id") or data.get("session_id")
        title = data.get("title", "")

        # Write initial pin immediately (async summary will update it)
        if thread_id:
            self._write_pin(thread_id, "正在整理摘要...", "done", False, task_id)
            await self.event_bus.emit(
                EventBus.PIN_CREATED,
                {"thread_id": thread_id, "task_id": task_id, "title": title, "status": "done"},
                caller="supervisor",
                agent_id="supervisor",
            )
            # Fire-and-forget async summary generation
            asyncio.create_task(
                self._generate_pin_summary(task_id, thread_id, title)
            )

        # Task 5: daily done counter and event-triggered report
        today = datetime.now(timezone.utc).date().isoformat()
        if self._daily_date != today:
            self._daily_done_count = 0
            self._daily_date = today
        self._daily_done_count += 1

        quality = await self.check_quality(data)
        self._quality[task_id] = quality
        level = "info" if quality["status"] == "pass" else "warning"
        self.memory.append_supervisor_log(
            event="task.done",
            title=data.get("title", ""),
            task_id=task_id,
            level=level,
            detail=quality["reason"],
        )
        if quality["status"] != "pass":
            # Task 3: auto-retry on quality failure
            retry_count = int(data.get("supervisor_retry_count") or 0) + 1
            if retry_count <= 2:
                self.memory.append_supervisor_log(
                    event="task.auto_retry",
                    title=data.get("title", ""),
                    task_id=task_id,
                    level="warning",
                    detail=f"质量检查未通过，自动重试（第 {retry_count} 次）。原因：{quality['reason']}",
                )
                self.retry_task(task_id, reason=f"quality_failed:{quality['reason']}")
            else:
                self.engine.todo_service.update(
                    task_id,
                    supervisor_quality=quality["status"],
                    supervisor_note=quality["reason"],
                )
                self.memory.add_supervisor_action_item(
                    text=f"需要人工复核：{data.get('title', '')}。已自动重试 {retry_count-1} 次仍未通过。{quality['reason']}",
                    task_id=task_id,
                    level="warning",
                )
        else:
            self.memory.append_supervisor_log(
                event="task.done",
                title=data.get("title", ""),
                task_id=task_id,
                level="info",
                detail=quality["reason"],
            )
            # Learn from successful session
            if thread_id:
                role = data.get("role") or "task_agent"
                await self._learn_from_session(task_id, thread_id, role)

        # Task 5: event-triggered report at 3+ task.done per day
        if self._daily_done_count >= 3:
            self._daily_done_count = 0
            await self._trigger_event_report(data.get("title", ""))

        await self.event_bus.emit(
            EventBus.SUPERVISOR_UPDATED,
            self.status(),
            caller="supervisor",
            agent_id="supervisor",
        )

    async def _on_task_added(self, event: AgentEvent) -> None:
        """New task detected — log observation."""
        data = event.payload
        self.memory.append_supervisor_log(
            event="task.added",
            title=data.get("task_title", ""),
            task_id=data.get("task_id"),
            level="info",
            detail="检测到新任务，即将执行",
        )

    async def _on_task_failed(self, event: AgentEvent) -> None:
        data = event.payload
        reason = data.get("error") or "未知错误"
        task_id = data.get("task_id", "")
        thread_id = data.get("session_thread_id") or data.get("session_id") or data.get("thread_id")

        # Write failed pin immediately
        if thread_id:
            self._write_pin(thread_id, f"任务失败：{reason}", "failed", False, task_id)
            await self.event_bus.emit(
                EventBus.PIN_CREATED,
                {"thread_id": thread_id, "status": "failed"},
                caller="supervisor",
                agent_id="supervisor",
            )

        self.memory.append_supervisor_log(
            event="task.failed",
            title=data.get("title", ""),
            task_id=task_id,
            level="error",
            detail=reason,
        )

        # Task 7: diagnose failed session
        if thread_id:
            diagnosis = await self._diagnose_failed_session(thread_id, data)
            if diagnosis:
                self.memory.add_supervisor_action_item(
                    text=f"失败诊断 - {data.get('title', '')}：{diagnosis}",
                    task_id=task_id,
                    level="error",
                )

        self.memory.add_supervisor_action_item(
            text=f"任务失败，需要处理：{data.get('title', '')}。原因：{reason}",
            task_id=task_id,
            level="error",
        )
        await self.event_bus.emit(
            EventBus.SUPERVISOR_UPDATED,
            self.status(),
            caller="supervisor",
            agent_id="supervisor",
        )

    async def _on_task_retrying(self, event: AgentEvent) -> None:
        data = event.payload
        self.memory.append_supervisor_log(
            event="task.retrying",
            title=data.get("title", ""),
            task_id=data.get("task_id"),
            level="warning",
            detail=f"第 {data.get('attempt')} 次重试",
        )

    async def _on_role_started(self, event: AgentEvent) -> None:
        data = event.payload
        self.memory.append_supervisor_log(
            event="role.started",
            title=data.get("title", ""),
            detail=f"{data.get('display_name') or data.get('role')} 开始处理",
            level="info",
        )

    async def _on_role_done(self, event: AgentEvent) -> None:
        data = event.payload
        self.memory.append_supervisor_log(
            event="role.done",
            title=data.get("title", ""),
            detail=f"{data.get('display_name') or data.get('role')} 完成",
            level="info",
        )

    async def _on_role_failed(self, event: AgentEvent) -> None:
        data = event.payload
        self.memory.append_supervisor_log(
            event="role.failed",
            title=data.get("title", ""),
            detail=f"{data.get('display_name') or data.get('role')} 失败：{data.get('error', '')}",
            level="error",
        )
        self.memory.add_supervisor_action_item(
            text=f"角色任务失败：{data.get('display_name') or data.get('role')} - {data.get('title', '')}",
            task_id=data.get("thread_id"),
            level="error",
        )

    async def check_quality(self, data: dict) -> dict:
        """Cheap quality gate for completed tasks.

        This deliberately avoids a mandatory LLM call. The LLM-based reviewer can
        be added later, but this catches the common false-done cases cheaply.
        """
        result = str(data.get("result") or "")
        summary = str(data.get("result_summary") or "")
        tools = data.get("tools_used") or []
        suspicious_tokens = [
            "[SubAgent 异常]",
            "[SubAgent 超时]",
            "Error executing",
            "Traceback",
            "未完成",
            "无法完成",
        ]
        if any(token in result for token in suspicious_tokens):
            return {"status": "needs_review", "reason": "输出中包含失败或未完成信号。"}
        if not result.strip() or result.strip() == "(no output)":
            return {"status": "needs_review", "reason": "任务没有产生有效输出。"}
        if not summary and len(result) < 20:
            return {"status": "needs_review", "reason": "输出过短，可能没有真正完成。"}
        if "Use your tools" in result and not tools:
            return {"status": "needs_review", "reason": "疑似只复述任务，没有使用工具或给出结果。"}

        # Optional LLM semantic check (disabled by default, controlled by config)
        sup_cfg = getattr(self.engine, "config", {}).get("supervisor", {})
        if sup_cfg.get("llm_quality_check", False):
            try:
                title = data.get("title", "")
                tools_str = ", ".join(tools) if tools else "(无)"
                prompt = (
                    f"任务：{title}\n"
                    f"工具调用：{tools_str}\n"
                    f"输出摘要：{(summary or result)[:500]}\n\n"
                    f"请判断任务是否真正完成（回答 pass 或 needs_review，并简要说明原因，不超过 50 字）。"
                )
                model = self.engine.model_router.get_model("utility")
                from langchain_core.messages import HumanMessage
                llm_result = await model.ainvoke([HumanMessage(content=prompt)])
                answer = (llm_result.content or "").strip().lower()
                if "needs_review" in answer or "未完成" in answer or "没有完成" in answer:
                    return {"status": "needs_review", "reason": f"LLM 语义检查未通过：{llm_result.content[:100]}"}
            except Exception:
                logger.debug("Supervisor: LLM quality check failed, falling back", exc_info=True)

        return {"status": "pass", "reason": "基础质量检查通过。"}

    def status(self) -> dict:
        tasks = self.engine.todo_service.list()
        roles = self.engine.role_loader.list_roles()
        counts = Counter(t.get("status", "unknown") for t in tasks)
        learning_highlights = self.learning_highlights()
        active_by_role = {
            (t.get("role") or "default"): t
            for t in tasks
            if t.get("status") == "in_progress"
        }
        team = []
        for role in roles:
            active_task = active_by_role.get(role.name)
            team.append({
                "name": role.name,
                "display_name": role.display_name,
                "description": role.description,
                "icon": role.icon,
                "personality": role.personality,
                "status_text": role.status_text or ("正在处理任务" if active_task else "待命"),
                "state": "busy" if active_task else "idle",
                "current_task_id": active_task.get("id") if active_task else None,
                "current_task_title": active_task.get("title") if active_task else None,
            })

        return {
            "thread_id": self.thread_id,
            "counts": {
                "pending": counts.get("pending", 0),
                "in_progress": counts.get("in_progress", 0),
                "done": counts.get("done", 0),
                "cancelled": counts.get("cancelled", 0),
            },
            "team": team,
            "action_items": self.action_items(),
            "learning_highlights": learning_highlights,
            "suggested_next_action": self.suggested_next_action(
                counts=counts,
                active_by_role=active_by_role,
                learning_highlights=learning_highlights,
            ),
            "quality": self._quality,
            "daily_report": self.daily_report(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def learning_highlights(self) -> list[dict[str, str]]:
        """Surface recent supervisor lessons in a UI-friendly shape."""
        dispatch_lessons = self.memory.read_role_dispatch(limit=6)
        role_health = self.memory.summarize_role_health(limit=8)
        role_health_map = {item["role"]: item for item in role_health}
        highlights: list[dict[str, str]] = []

        for lesson in reversed(dispatch_lessons):
            health = role_health_map.get(lesson["role"], {})
            role_obj = self.engine.role_loader.get(lesson["role"])
            success_rate = health.get("success_rate")
            if success_rate is None:
                confidence = "observed"
            elif success_rate >= 0.8:
                confidence = "strong"
            elif success_rate >= 0.5:
                confidence = "steady"
            else:
                confidence = "mixed"
            highlights.append({
                "role": role_obj.display_name if role_obj is not None else lesson["role"],
                "task_type": lesson["task_type"],
                "tools_chain": lesson["tools_chain"],
                "confidence": confidence,
            })
        return highlights[:4]

    def suggested_next_action(
        self,
        *,
        counts: Counter,
        active_by_role: dict[str, dict],
        learning_highlights: list[dict[str, str]],
    ) -> str:
        """Provide one supervisor recommendation that closes the learning loop."""
        if counts.get("in_progress", 0) > 0:
            role_name, task = next(iter(active_by_role.items()))
            role_obj = self.engine.role_loader.get(role_name)
            role_label = role_obj.display_name if role_obj is not None else role_name
            return (
                f"先盯住当前推进中的任务：{task.get('title', '')}。"
                f" 如需补位，优先围绕 {role_label} 这条线推进。"
            )

        if counts.get("pending", 0) > 0:
            pending = [t for t in self.engine.todo_service.list() if t.get("status") == "pending"]
            top = pending[0] if pending else None
            if top and learning_highlights:
                lesson = learning_highlights[0]
                return (
                    f"前台还有待办，下一步可优先处理“{top.get('title', '')}”。"
                    f" 最近 {lesson['role']} 在“{lesson['task_type']}”上表现{lesson['confidence']}，可优先考虑派给他。"
                )
            if top:
                return f"前台还有待办，建议先推进“{top.get('title', '')}”。"

        if learning_highlights:
            lesson = learning_highlights[0]
            return (
                f"最近学到的一条经验：{lesson['role']} 更适合处理“{lesson['task_type']}”，"
                f" 常用链路是 {lesson['tools_chain']}。"
            )

        return "当前没有紧急阻塞，可以直接交办下一件事。"

    def action_items(self) -> list[dict]:
        items = self.memory.read_supervisor_action_items(limit=10)
        pending = [t for t in self.engine.todo_service.list() if t.get("status") == "pending"]
        if pending:
            items.append({
                "level": "info",
                "text": f"{len(pending)} 个任务等待接手，可点击立即执行唤醒团队。",
            })
        return items[-10:]

    def daily_report(self) -> str:
        """Generate daily report and push via IM if available."""
        tasks = self.engine.todo_service.list()
        today = datetime.now(timezone.utc).date().isoformat()
        todays = [
            t for t in tasks
            if str(t.get("completed_at") or "").startswith(today)
            or str(t.get("created_at") or "").startswith(today)
        ]
        done = [t for t in todays if t.get("status") == "done"]
        active = [t for t in todays if t.get("status") == "in_progress"]
        pending = [t for t in todays if t.get("status") == "pending"]
        lines = [f"# 今日工作简报 ({today})", ""]
        lines.append(f"- 已完成: {len(done)}")
        lines.append(f"- 进行中: {len(active)}")
        lines.append(f"- 待接手: {len(pending)}")
        if done:
            lines += ["", "## 已完成"]
            for task in done[:8]:
                lines.append(f"- {task.get('title', '')} ({task.get('role') or 'default'})")
        if active:
            lines += ["", "## 正在推进"]
            for task in active[:5]:
                lines.append(f"- {task.get('title', '')} ({task.get('role') or 'default'})")
        if pending:
            lines += ["", "## 待接手"]
            for task in pending[:5]:
                lines.append(f"- {task.get('title', '')}")

        report = "\n".join(lines)

        # Task 6: push via im_notify if IM bridge is available
        self._push_to_im(report)

        # Log to daily_log
        self.memory.append_supervisor_log(
            event="daily_report",
            title=f"日报 ({today})",
            detail=f"已完成 {len(done)}, 进行中 {len(active)}, 待接手 {len(pending)}",
            level="info",
        )

        return report

    async def _trigger_event_report(self, latest_title: str) -> None:
        """Trigger a report when 3+ tasks completed in one day."""
        report = self.daily_report()
        self.memory.append_supervisor_log(
            event="event_report",
            title="事件触发汇报",
            detail=f"今日第 {self._daily_date} 日第 3+ 任务完成，自动生成汇报。最新：{latest_title}",
            level="info",
        )

    def _push_to_im(self, content: str) -> None:
        """Task 6: push report content to IM targets via im_notify tool."""
        try:
            # Check if IM bridge is connected
            if not hasattr(self.engine, "bridge") or not self.engine.bridge._adapters:
                logger.debug("Supervisor: no IM bridge, skipping push")
                return

            # Find im_notify tool in registry
            tool_fn = self.engine.registry._tools.get("im_notify")
            if tool_fn is None:
                logger.debug("Supervisor: im_notify tool not registered, skipping push")
                return

            # Push to configured IM target ("me" = user)
            import inspect
            sig = inspect.signature(tool_fn)
            params = list(sig.parameters.keys())
            if "target" in params:
                result = tool_fn(target="me", content=content)
            else:
                result = tool_fn(content=content)
            logger.info("Supervisor: IM push result: %s", result)
        except Exception:
            logger.debug("Supervisor: IM push failed, silently ignored", exc_info=True)

    def retry_task(self, task_id: str, reason: str = "supervisor") -> dict:
        """Reset a task to pending and wake the executor.

        Accepts either a todo task ID or a session thread_id (e.g. subagent
        sessions). When a session thread_id is given, tries to find the parent
        todo task by matching session names.
        """
        # Case 1: direct todo task ID
        task = self.engine.todo_service.get(task_id)
        if task is not None:
            return self._do_retry(task, reason)

        # Case 2: session thread_id — find parent todo task
        session_mgr = getattr(self.engine, "session_manager", None)
        if session_mgr is not None:
            session = session_mgr.get_session(task_id)
            if session is not None:
                parent_task = self._find_task_by_session(task_id, session)
                if parent_task is not None:
                    result = self._do_retry(parent_task, reason)
                    # Clear the stale action_item that referenced this session
                    self.memory.remove_action_items_for_task_id(task_id)
                    return result

        return {"ok": False, "error": f"Task or session '{task_id}' not found"}

    def _do_retry(self, task: dict, reason: str) -> dict:
        """Perform the actual retry on a todo task."""
        task_id = task["id"]
        retry_count = int(task.get("supervisor_retry_count") or 0) + 1
        updated = self.engine.todo_service.update(
            task_id,
            status="pending",
            supervisor_retry_count=retry_count,
            supervisor_note=reason,
        )
        self.memory.append_supervisor_log(
            event="task.retry_requested",
            title=task.get("title", ""),
            task_id=task_id,
            level="warning",
            detail=reason,
        )
        self.engine.wakeup_executor(reason=f"supervisor:{reason}")
        return {"ok": True, "task": updated, "retry_count": retry_count}

    def _find_task_by_session(self, thread_id: str, session: dict) -> dict | None:
        """Find a todo task whose session matches the given thread_id.

        Tries exact match first, then fuzzy match on the session name.
        For subagent sessions like 'sub-Shen Heng-daily news digest', extracts the
        base title and searches for a matching todo task.
        """
        # Try exact match on session_thread_id
        for task in self.engine.todo_service.list():
            if task.get("session_thread_id") == thread_id:
                return task

        # Fuzzy match: extract title from session name and search
        session_name = session.get("name", "")
        base = session_name.removeprefix("sub-")
        if not base:
            return None

        for task in self.engine.todo_service.list():
            task_title = task.get("title", "")
            # Check if todo task title is contained in the session name
            # e.g. 'daily news digest' in 'Shen Heng - daily news digest'
            if task_title and task_title in base:
                return task

            # Also check session_thread_id patterns
            # e.g. 'daily news digest' in 'task-daily news digest-14'
            task_session = task.get("session_thread_id", "")
            if task_session and task_title and task_title in task_session and task_title in base:
                return task

        return None

    async def memory_maintenance(self) -> dict:
        # Task 8: clean expired execution logs
        cleaned = self._clean_expired_logs()

        patterns = await self.memory.distill_patterns()
        insights = await self.memory.distill_insights()
        self.memory.append_supervisor_log(
            event="memory.maintenance",
            title="记忆维护",
            detail=(
                f"patterns={'已更新' if patterns else '暂无'}，"
                f"insights={'已更新' if insights else '暂无'}，"
                f"清理 {cleaned} 条过期日志"
            ),
        )
        return {
            "ok": True,
            "patterns_updated": bool(patterns),
            "insights_updated": bool(insights),
            "lines_cleaned": cleaned,
        }

    def _clean_expired_logs(self) -> int:
        """Task 8: remove execution_log lines older than 30 days."""
        import json as _json
        from pathlib import Path as _Path

        log_path = self.memory._memory_dir / TASK_EXPERIENCE_DIR / EXECUTION_LOG_FILE
        if not log_path.exists():
            return 0

        cutoff = datetime.now(timezone.utc).date() - timedelta(days=30)
        kept = 0
        removed = 0
        lines = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = _json.loads(line)
                ts_str = record.get("ts", "")
                if ts_str:
                    ts_date = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).date()
                    if ts_date >= cutoff:
                        kept += 1
                        lines.append(line)
                    else:
                        removed += 1
                else:
                    kept += 1
                    lines.append(line)
            except (_json.JSONDecodeError, ValueError):
                kept += 1
                lines.append(line)

        if removed > 0:
            log_path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")
            self.memory.append_supervisor_log(
                event="log.cleanup",
                title="过期日志清理",
                detail=f"保留 {kept} 条，删除 {removed} 条（>30天）",
                level="info",
            )
        return removed

    async def _learn_from_session(self, task_id: str, thread_id: str, role: str) -> None:
        """Read a successful session and distill role dispatch lessons into role_dispatch.md."""
        try:
            agent = self.engine.agent
            config = {"configurable": {"thread_id": thread_id}}
            state = agent.get_state(config)
            if state is None or "messages" not in state:
                return

            messages = state["messages"]
            tool_calls = []
            for msg in messages:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_calls.append(tc.get("name", ""))

            if not tool_calls:
                return

            tools_chain = " → ".join(tool_calls[:8])
            task_data = self.engine.todo_service.get(task_id) or {}
            title = task_data.get("title", "")

            prompt = (
                f"一个 [{role}] 角色刚刚成功完成任务：「{title}」\n"
                f"工具调用序列：{tools_chain}\n\n"
                f"请用一句话总结这个角色适合的任务类型（不超过 15 字）。"
            )
            model = self.engine.model_router.get_model("utility")
            from langchain_core.messages import HumanMessage
            result = await model.ainvoke([HumanMessage(content=prompt)])
            task_type = (result.content or "").strip()[:50] if result else ""

            if task_type:
                self.memory.append_role_dispatch(
                    role=role,
                    task_type=task_type,
                    tools_chain=tools_chain,
                )
                logger.info("Supervisor: learned dispatch lesson for role=%s task_type=%s", role, task_type)
        except Exception:
            logger.debug("Supervisor: _learn_from_session failed silently", exc_info=True)

    async def _diagnose_failed_session(self, thread_id: str, data: dict) -> str:
        """Task 7: read failed session history and analyze failure cause."""
        try:
            agent = self.engine.agent
            config = {"configurable": {"thread_id": thread_id}}
            state = agent.get_state(config)
            if state is None or "messages" not in state:
                return "无法读取 session 对话历史。"

            messages = state["messages"]
            # Extract tool calls and errors
            tool_calls = []
            last_error = data.get("error", "")
            for msg in messages:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_calls.append(f"- 工具: {tc.get('name', '')}, 参数: {str(tc.get('args', ''))[:200]}")
                if hasattr(msg, "content") and msg.content:
                    content_preview = str(msg.content)[:300].replace("\n", " ")

            diagnosis_prompt = (
                f"以下是一个任务执行失败的 session 完整对话历史。\n\n"
                f"任务标题: {data.get('title', '')}\n"
                f"错误信息: {last_error}\n\n"
                f"工具调用记录:\n" + "\n".join(tool_calls[:10]) + "\n\n"
                f"请简要分析：\n"
                f"1. 失败的根本原因是什么？\n"
                f"2. 如果是工具调用错误，具体错误是什么？\n"
                f"3. 给出修复建议。\n"
                f"请用中文回答，不超过 200 字。"
            )

            # Use utility model for cheap analysis
            model = self.engine.model_router.get_model("utility")
            from langchain_core.messages import HumanMessage
            result = await model.ainvoke([HumanMessage(content=diagnosis_prompt)])
            analysis = result.content if result and result.content else "分析无结果。"
            return analysis
        except Exception:
            logger.debug("Supervisor: session diagnosis failed", exc_info=True)
            return f"诊断读取失败：{last_error}"

    def _write_pin(
        self, thread_id: str, summary: str, status: str, read: bool,
        task_id: str = "",
    ) -> None:
        """Write or update pin metadata for a session."""
        sm = self.engine.session_manager
        meta = sm._data["sessions"].get(thread_id)
        if meta is None:
            logger.warning("Cannot write pin: thread_id %s not found", thread_id)
            return
        now = datetime.now(timezone.utc).isoformat()
        meta["pin"] = {
            "summary": summary,
            "status": status,
            "created_at": now,
            "read": read,
            "task_id": task_id,
        }
        sm._save_index()
        logger.info("Pin written for thread %s (status=%s, task_id=%s)", thread_id, status, task_id)

    async def _generate_pin_summary(
        self, task_id: str, thread_id: str, task_title: str
    ) -> None:
        """Async task: generate pin summary and update session metadata."""
        summary = await generate_pin_summary(
            self.engine, thread_id, task_title
        )
        # Update pin with the generated summary
        sm = self.engine.session_manager
        meta = sm._data["sessions"].get(thread_id)
        if meta and meta.get("pin"):
            meta["pin"]["summary"] = summary
            sm._save_index()
            logger.info(
                "Pin summary updated for thread %s: %s", thread_id, summary[:50]
            )
            # Push update via event bus for real-time frontend refresh
            await self.event_bus.emit(
                EventBus.PIN_UPDATED,
                {
                    "thread_id": thread_id,
                    "task_id": task_id,
                    "summary": summary,
                    "title": task_title,
                },
                caller="supervisor",
                agent_id="supervisor",
            )

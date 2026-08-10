"""Pin summarizer — generates task completion summaries for homepage pins."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """\
请根据以下对话历史的最后部分，用 100 字以内的中文总结任务结果。
重点关注：完成了什么、关键结论是什么、有没有需要用户注意的风险或待决定事项。
如果有文件产出，注明文件路径。

对话片段：
{messages}
"""


def _format_messages_for_summary(messages: list) -> str:
    """Convert LangGraph messages to a text block for the summary prompt.

    Handles both live LangChain message objects and deserialized dicts
    (common when loading from the SQLite checkpointer after task completion).
    """
    parts = []
    for msg in messages[-20:]:
        if isinstance(msg, dict):
            msg_type = msg.get("type", "")
            content = msg.get("content", "")
            if msg_type == "human" or msg.get("role") == "user":
                role = "user"
            elif msg_type == "ai":
                role = "assistant"
            elif msg_type == "tool" or msg.get("role") == "tool":
                role = "tool"
            else:
                role = msg_type or "unknown"
        else:
            role = getattr(msg, "type", "unknown")
            content = getattr(msg, "content", "")

        if isinstance(content, (list, dict)):
            import json
            content = json.dumps(content, ensure_ascii=False)
        elif content is None:
            content = ""
        content = str(content)

        if len(content) > 200:
            content = content[:200] + "..."
        parts.append(f"[{role}] {content}")
    return "\n".join(parts)


async def generate_pin_summary(
    engine: Any,
    thread_id: str,
    task_title: str,
    timeout: float = 30.0,
) -> str:
    """Generate a summary for a task completion pin.

    Args:
        engine: WorkPartnerEngine instance for model access.
        thread_id: The session thread_id to load messages from.
        task_title: Fallback title if summarization fails.
        timeout: Max seconds to wait for the model response.

    Returns:
        Summary string, or task_title on failure.
    """
    try:
        # Load session messages
        if engine.agent is None:
            return task_title

        snapshot = engine.agent.get_state(
            {"configurable": {"thread_id": thread_id}}
        )
        if snapshot is None or not snapshot.values:
            return task_title

        messages = snapshot.values.get("messages", [])
        if not messages:
            return task_title

        msg_text = _format_messages_for_summary(messages)
        prompt = SUMMARY_PROMPT.format(messages=msg_text)

        # Use utility model for cheap/fast summary
        model = engine.model_router.get_model("utility")
        if model is None:
            return task_title

        async def _call_model():
            response = await model.ainvoke([("user", prompt)])
            return getattr(response, "content", task_title)

        result = await asyncio.wait_for(_call_model(), timeout=timeout)
        summary = str(result).strip()
        if not summary or len(summary) > 200:
            summary = summary[:200] if summary else task_title
        return summary

    except asyncio.TimeoutError:
        logger.warning("Pin summary generation timed out for thread %s", thread_id)
        return task_title
    except Exception as e:
        logger.error("Pin summary generation failed for thread %s: %s", thread_id, e)
        return task_title

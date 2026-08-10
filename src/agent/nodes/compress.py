"""Context compression node: structured summaries for long conversations."""

import logging
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from ..state import AgentState

logger = logging.getLogger(__name__)


async def compress_node(
    state: AgentState,
    *,
    model: ChatOpenAI,
    threshold: int = 30,
    keep_recent: int = 5,
    summary_model: ChatOpenAI | None = None,
    **kwargs: Any,
) -> dict:
    """Summarize older messages when the conversation grows too long.

    The summary uses a stable multi-section shape so later turns can recover
    decisions, paths, risks, and open tasks without treating raw logs as memory.
    """
    messages = state["messages"]
    existing_summary = state.get("compression_summary")

    if len(messages) <= threshold:
        return {}

    sum_model = summary_model if summary_model is not None else model
    old_msgs = messages[:-keep_recent]

    prev_context = ""
    if existing_summary:
        prev_context = (
            f"\nPrevious structured summary (fold its still-relevant facts into "
            f"your new output — do not just append to it):\n{existing_summary}\n"
        )

    formatted = _format_for_summary(old_msgs)

    prompt = f"""Summarize the conversation history below into the exact structured
format requested. Be dense but lossless: capture every decision, fact,
preference, pending task, file path, tool result, and risk that may matter later.

{prev_context}

Use these sections exactly:

## 1. Current Goal
- What the user is trying to accomplish now.

## 2. Decisions
- Decisions made and the reason for each.

## 3. Stable Facts And Paths
- File paths, config values, APIs, data shapes, and project facts.

## 4. User Preferences
- Durable preferences about style, language, workflow, or constraints.

## 5. Code And Tool Changes
- Concrete edits, commands, tests, and their outcomes.

## 6. Open Tasks
- Remaining work, blockers, or questions.

## 7. Risks And Constraints
- Permissions, dirty worktree notes, compatibility concerns, and failure modes.

## 8. Event And Trace Notes
- Important event names, task/session ids, trace ids, or caller/agent context.

## 9. Recent Outcome
- The latest state after the summarized messages.

<history>
{formatted}
</history>

Write in the user's language. Keep it compact, but do not merge sections."""

    try:
        response: Any = await sum_model.ainvoke([HumanMessage(content=prompt)])
        new_summary = response.content
    except Exception as exc:
        # Non-critical path: a failed compression must not crash the session.
        # Keep the existing summary (if any) and let messages keep accumulating
        # until the next successful compression attempt.
        logger.warning("compress_node: LLM call failed, skipping compression: %s", exc)
        return {}

    # The model is instructed to fold prev_context into new_summary directly,
    # so we use it as-is rather than concatenating — repeated concatenation
    # across many compressions would otherwise make the summary itself grow
    # without bound.
    return {"compression_summary": new_summary}


def _format_for_summary(messages: list) -> str:
    """Format messages compactly for the summarization prompt."""
    lines = []
    for msg in messages:
        role = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", str(msg))
        if isinstance(content, list):
            content = " ".join(
                b.get("text", "") for b in content if b.get("type") == "text"
            )
        content = str(content)[:2000]
        lines.append(f"[{role}] {content}")
    return "\n\n".join(lines)

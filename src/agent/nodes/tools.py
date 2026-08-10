"""Tool execution node — runs tool calls and returns results."""

import json
from typing import Any

from langchain_core.messages import ToolMessage

from ..state import AgentState
from ...tools.registry import ToolRegistry


async def tool_node(state: AgentState, *, registry: ToolRegistry, **kwargs: Any) -> dict:
    """Execute all pending tool calls from the last AIMessage.

    Each tool call is dispatched to the ToolRegistry. If the result is a
    JSON string with an 'image' key, a multimodal ToolMessage is created
    so the LLM can "see" the image. Otherwise a plain text ToolMessage.
    """
    messages = state["messages"]
    if not messages:
        return {}

    last_msg = messages[-1]
    tool_calls = getattr(last_msg, "tool_calls", None)
    if not tool_calls:
        return {}

    tool_messages = []
    tool_summaries = []
    for tc in tool_calls:
        name = tc.get("name", "")
        args = tc.get("args", {})
        call_id = tc.get("id", "")

        result = await registry.execute_result(name, args)
        status = "ok" if result.success else f"error:{result.error or 'unknown'}"
        tool_summaries.append(f"{name}({status})")

        # Detect multimodal content: tool returns JSON with image data
        content = _build_message_content(result.content)
        tool_messages.append(
            ToolMessage(content=content, tool_call_id=call_id, name=name)
        )

    return {
        "messages": tool_messages,
        "last_tool_summary": ", ".join(tool_summaries),
    }


def _build_message_content(result: str) -> str | list[dict]:
    """Parse tool result. If it contains image data, return multimodal content blocks
    so multimodal models can process the image. Otherwise return the raw string."""
    try:
        data = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return str(result)

    if not isinstance(data, dict) or "image" not in data:
        return str(result)

    img_info = data["image"]
    b64 = img_info.get("base64", "")
    mime = img_info.get("mime", "image/png")

    if not b64:
        return str(result)

    blocks = []
    if data.get("text"):
        blocks.append({"type": "text", "text": data["text"]})
    blocks.append({
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{b64}"},
    })
    return blocks

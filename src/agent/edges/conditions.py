from ..state import AgentState


def has_tool_calls(state: AgentState) -> str:
    """Route after chat_node: tool_node if there are tool calls, else respond."""
    messages = state["messages"]
    if not messages:
        return "respond"
    last_msg = messages[-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return "respond"


def should_compress(state: AgentState, threshold: int = 30) -> str:
    """Route before chat_node: compress if messages exceed threshold.

    Compression is re-triggered when the message count grows significantly
    beyond the last compression point.
    """
    messages = state["messages"]
    if len(messages) <= threshold:
        return "chat"

    # Re-compress only if messages doubled since last compression. (Tripling
    # left a 2x-threshold window of uncompressed growth in between.)
    existing = state.get("compression_summary")
    if existing and len(messages) < threshold * 2:
        return "chat"

    return "compress"

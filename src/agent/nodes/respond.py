from ..state import AgentState


async def respond_node(state: AgentState) -> dict:
    """Terminal node — the response is already in messages from chat_node.

    No modifications needed; this is a pass-through end state.
    """
    return {}

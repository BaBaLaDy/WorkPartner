from typing import Any

from langchain_core.messages import AIMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ..state import AgentState


async def chat_node(
    state: AgentState, *, model: ChatOpenAI, registry=None, **kwargs: Any
) -> dict:
    """Call the LLM with current messages + system prompt + compression context.

    When compression_summary is set (Phase 3), only the last few messages are
    sent alongside the summary — drastically reducing token consumption.

    If registry is provided, tools are read dynamically from the registry
    instead of the state snapshot — enabling MCP runtime tool injection.
    """
    summary = state.get("compression_summary")
    all_messages = list(state["messages"])
    keep_recent = kwargs.get("compression_keep_recent", 5)

    # Build the message list for the LLM
    llm_messages = [SystemMessage(content=state["system_prompt"])]

    if summary:
        # Inject the compression summary as context
        llm_messages.append(
            SystemMessage(
                content=f"[Context from earlier conversation]\n{summary}"
            )
        )
        # Only send the most recent messages (the rest are summarized)
        recent = list(all_messages[-keep_recent:]) if len(all_messages) > keep_recent else list(all_messages)

        # Ensure the message list starts with a user message (API requirement).
        # If compression sliced off the initial HumanMessage, prepend one.
        from langchain_core.messages import HumanMessage
        has_user = any(isinstance(m, HumanMessage) for m in recent)
        if not has_user:
            # Find the most recent HumanMessage from older messages
            older = all_messages[:-keep_recent] if len(all_messages) > keep_recent else []
            for m in reversed(older):
                if isinstance(m, HumanMessage):
                    recent.insert(0, m)
                    break

        llm_messages.extend(recent)
    else:
        llm_messages.extend(all_messages)

    # Bind tools — prefer dynamic registry over state snapshot
    tools = registry.as_openai_tools() if registry else state.get("tools", [])
    if tools:
        model_with_tools = model.bind_tools(tools)
        response: AIMessage = await model_with_tools.ainvoke(llm_messages)
    else:
        response: AIMessage = await model.ainvoke(llm_messages)

    return {"messages": [response]}

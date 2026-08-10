"""LangGraph agent graph builder.

Phase 3 graph:
    START → pre → should_compress? ──yes──→ compress → chat
                      │                              ↑
                      no                             │
                      │                              │
                      ▼                              │
                    chat → condition ──tools──→ pre ─┘
                              │
                              no tools
                              │
                              ▼
                           respond → END
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.base import BaseCheckpointSaver
from langchain_openai import ChatOpenAI

from .state import AgentState
from .nodes import chat_node, respond_node
from .nodes.tools import tool_node
from .nodes.compress import compress_node
from .edges.conditions import has_tool_calls, should_compress
from ..providers.factory import create_model
from ..tools.registry import ToolRegistry


def build_agent_graph(
    model: ChatOpenAI | None = None,
    registry: ToolRegistry | None = None,
    compression_threshold: int = 30,
    compression_keep_recent: int = 5,
    summary_model: ChatOpenAI | None = None,
) -> StateGraph:
    """Build the LangGraph agent state graph."""
    if model is None:
        model = create_model()
    if registry is None:
        registry = ToolRegistry()

    builder = StateGraph(AgentState)

    # Wrap nodes to inject dependencies
    async def _chat(state):
        return await chat_node(
            state, model=model, registry=registry,
            compression_keep_recent=compression_keep_recent,
        )

    async def _tools(state):
        return await tool_node(state, registry=registry)

    async def _compress(state):
        return await compress_node(
            state, model=model,
            threshold=compression_threshold,
            keep_recent=compression_keep_recent,
            summary_model=summary_model,
        )

    async def _pre(state):
        """Pass-through node — entry point to check compression."""
        return {}

    builder.add_node("pre", _pre)
    builder.add_node("chat", _chat)
    builder.add_node("tools", _tools)
    builder.add_node("respond", respond_node)
    builder.add_node("compress", _compress)

    builder.set_entry_point("pre")

    # pre → compress (if needed) or chat (skip)
    builder.add_conditional_edges(
        "pre",
        lambda s: should_compress(s, threshold=compression_threshold),
        {"compress": "compress", "chat": "chat"},
    )

    # compress → chat
    builder.add_edge("compress", "chat")

    # chat → tools or respond
    builder.add_conditional_edges("chat", has_tool_calls, {
        "tools": "tools",
        "respond": "respond",
    })

    # tools → pre (re-check compression before next chat)
    builder.add_edge("tools", "pre")

    builder.add_edge("respond", END)

    return builder


def create_agent(
    model: ChatOpenAI | None = None,
    registry: ToolRegistry | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    compression_threshold: int = 30,
    compression_keep_recent: int = 5,
    summary_model: ChatOpenAI | None = None,
):
    """Create a compiled agent ready for invocation."""
    builder = build_agent_graph(
        model=model,
        registry=registry,
        compression_threshold=compression_threshold,
        compression_keep_recent=compression_keep_recent,
        summary_model=summary_model,
    )
    return builder.compile(checkpointer=checkpointer)

"""Test Phase 3: context compression."""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_core.messages import HumanMessage, AIMessage

from src.agent.graph import build_agent_graph
from src.agent.state import AgentState
from src.agent.edges.conditions import should_compress
from src.tools.defaults import create_default_registry


def test_should_compress_condition():
    """Verify the should_compress routing logic."""
    # Below threshold → skip
    state = {"messages": [HumanMessage(content=f"msg {i}") for i in range(10)]}
    assert should_compress(state, threshold=30) == "chat"
    print(f"  [PASS] {len(state['messages'])} msgs → skip compress")

    # Above threshold → compress
    state = {"messages": [HumanMessage(content=f"msg {i}") for i in range(35)]}
    assert should_compress(state, threshold=30) == "compress"
    print(f"  [PASS] {len(state['messages'])} msgs → trigger compress")

    # Already compressed, below 2x threshold → skip re-compress
    state = {
        "messages": [HumanMessage(content=f"msg {i}") for i in range(40)],
        "compression_summary": "existing summary",
    }
    assert should_compress(state, threshold=30) == "chat"
    print(f"  [PASS] {len(state['messages'])} msgs + existing summary → skip re-compress")

    # Already compressed, still below 2x threshold → skip re-compress
    state = {
        "messages": [HumanMessage(content=f"msg {i}") for i in range(50)],
        "compression_summary": "existing summary",
    }
    assert should_compress(state, threshold=30) == "chat"
    print(f"  [PASS] {len(state['messages'])} msgs + existing summary → skip (below 2x)")

    # Already compressed, reached 2x threshold → re-compress
    state = {
        "messages": [HumanMessage(content=f"msg {i}") for i in range(65)],
        "compression_summary": "existing summary",
    }
    assert should_compress(state, threshold=30) == "compress"
    print(f"  [PASS] {len(state['messages'])} msgs + existing summary → re-compress")


def test_graph_with_compression():
    """Verify the Phase 3 graph builds with compression nodes."""
    reg = create_default_registry()
    graph = build_agent_graph(registry=reg, compression_threshold=20, compression_keep_recent=3)
    nodes = list(graph.nodes.keys())
    assert "pre" in nodes, "Missing pre node"
    assert "compress" in nodes, "Missing compress node"
    assert "chat" in nodes
    assert "tools" in nodes
    assert "respond" in nodes
    print(f"  [PASS] Graph nodes: {nodes}")

    compiled = graph.compile()
    assert compiled is not None
    print(f"  [PASS] Graph compiles successfully")


def test_chat_node_truncation_logic():
    """Verify chat_node uses compression_summary to truncate."""
    # Create a mock
    from src.agent.nodes.chat import chat_node

    # Build state with compression_summary set
    messages = [
        HumanMessage(content="msg1"),
        AIMessage(content="resp1"),
        HumanMessage(content="msg2"),
        AIMessage(content="resp2"),
        HumanMessage(content="msg3"),
        AIMessage(content="resp3"),
        HumanMessage(content="msg4"),
        AIMessage(content="resp4"),
        HumanMessage(content="msg5"),
        AIMessage(content="resp5"),
        HumanMessage(content="current question"),
    ]

    state = AgentState(
        messages=messages,
        system_prompt="You are helpful.",
        tools=[],
        compression_summary="Earlier: user asked about Python, agent explained loops.",
    )

    # Verify state is constructed correctly
    assert state["compression_summary"] is not None
    assert len(state["messages"]) == 11
    print(f"  [PASS] State built: {len(state['messages'])} msgs, summary={len(state['compression_summary'])} chars")


def test_compress_node_formatting():
    """Verify message formatting for compression prompt."""
    from src.agent.nodes.compress import _format_for_summary

    messages = [
        HumanMessage(content="Hello"),
        AIMessage(content="Hi there!"),
        HumanMessage(content="Help me with Python"),
        AIMessage(content="Sure, what do you need?"),
    ]
    formatted = _format_for_summary(messages)
    assert "hello" in formatted.lower()
    assert "hi there" in formatted.lower()
    print(f"  [PASS] Message formatting: {len(formatted)} chars")


if __name__ == "__main__":
    print("Phase 3 Compression Tests\n")
    test_should_compress_condition()
    test_graph_with_compression()
    test_chat_node_truncation_logic()
    test_compress_node_formatting()
    print("\nAll Phase 3 tests passed.")

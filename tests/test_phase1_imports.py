"""Phase 1 — verify config loading, all imports, and graph construction."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_config_loads():
    """config.yaml loads and exposes the expected providers section."""
    from src.providers.factory import load_config

    config = load_config()
    assert "providers" in config
    assert config["providers"].get("default") == "openai"


def test_core_imports():
    """Core agent modules import cleanly."""
    from src.agent.graph import build_agent_graph  # noqa: F401
    from src.agent.state import AgentState  # noqa: F401
    from src.core.engine import WorkPartnerEngine  # noqa: F401
    from src.providers.factory import create_model  # noqa: F401


def test_graph_compiles():
    """The LangGraph state graph builds and compiles."""
    from src.agent.graph import build_agent_graph

    graph = build_agent_graph()
    compiled = graph.compile()
    assert compiled is not None
    assert "chat" in graph.nodes


if __name__ == "__main__":
    # Keep the original smoke-script behaviour for quick manual checks.
    test_config_loads()
    test_core_imports()
    test_graph_compiles()
    print("Phase 1 setup verified")

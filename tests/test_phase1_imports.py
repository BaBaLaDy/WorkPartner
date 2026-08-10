"""Smoke test for Phase 1 — verify all imports and graph construction."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.providers.factory import create_model, load_config
from src.agent.graph import build_agent_graph
from src.agent.state import AgentState

print("All imports OK")

config = load_config()
print(f"Provider: {config['providers']['default']}")
print(f"Model: {config['providers']['openai']['model']}")

graph = build_agent_graph()
compiled = graph.compile()
print(f"Graph nodes: {list(graph.nodes.keys())}")
print("Phase 1 setup verified")

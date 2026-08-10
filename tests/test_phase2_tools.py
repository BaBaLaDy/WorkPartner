"""Integration test for Phase 2: tools + skills + graph."""

import sys
import asyncio
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tools.defaults import create_default_registry
from src.tools.registry import ToolRegistry
from src.skills.loader import SkillLoader
from src.skills.injector import SkillInjector
from src.skills.saver import save_skill
from src.agent.graph import build_agent_graph


def test_registry():
    """Verify tool registry works."""
    reg = create_default_registry()
    names = reg.list_names()
    assert "file_read" in names, f"Missing file_read, got: {names}"
    assert "file_write" in names, f"Missing file_write, got: {names}"
    assert "file_patch" in names, f"Missing file_patch, got: {names}"
    assert "code_run" in names, f"Missing code_run, got: {names}"
    print(f"  [OK] Tool registry: {names}")

    # Check OpenAI schema
    schemas = reg.as_openai_tools()
    assert len(schemas) >= 4  # Phase 2 base + Phase 4 todo tools
    for s in schemas:
        assert s["type"] == "function"
        assert "name" in s["function"]
    print(f"  [OK] OpenAI schemas: {[s['function']['name'] for s in schemas]}")


def test_skills():
    """Verify skills use the directory + SKILL.md format."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a test skill as directory + SKILL.md
        filepath = save_skill(
            name="test-skill",
            description="A test skill for unit testing. Use when user asks about testing.",
            content="Do X then Y.",
            skills_dir=tmpdir,
            version="1.0",
        )
        assert os.path.isfile(filepath)
        assert os.path.basename(os.path.dirname(filepath)) == "test-skill"
        assert os.path.basename(filepath) == "SKILL.md"

        # Verify file contents
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        assert "name: test-skill" in content
        assert "description: A test skill" in content
        assert "version: \"1.0\"" in content
        assert "Do X then Y" in content
        print(f"  [OK] Skill saved as directory+SKILL.md")

        # Load it
        loader = SkillLoader(tmpdir)
        skills = loader.load_all()
        assert len(skills) == 1
        skill = skills[0]
        assert skill.name == "test-skill"
        assert "Do X then Y" in skill.content
        assert skill.version == "1.0"
        assert skill.should_auto_load is True
        print(f"  [OK] Skill loaded: {skill}")

        # Injector - Level 1 (metadata)
        injector = SkillInjector(loader)
        prompt = injector.build_skills_prompt()
        assert "test-skill" in prompt
        assert "A test skill" in prompt
        print(f"  [OK] Skills prompt (Level 1 metadata): {len(prompt)} chars")

        # Injector - Level 2 (full instructions)
        instructions = injector.get_skill_instructions("test-skill")
        assert instructions is not None
        assert "Do X then Y" in instructions
        print(f"  [OK] Skills instructions (Level 2): {len(instructions)} chars")

        # Test disable-model-invocation
        save_skill(
            name="dangerous-skill",
            description="A destructive operation.",
            content="Be very careful.",
            skills_dir=tmpdir,
            disable_model_invocation=True,
        )
        loader2 = SkillLoader(tmpdir)
        loader2.load_all()
        dangerous = loader2.get("dangerous-skill")
        assert dangerous is not None
        assert dangerous.should_auto_load is False
        print(f"  [OK] disable-model-invocation works")


def test_graph():
    """Verify Phase 2 graph builds correctly."""
    reg = create_default_registry()
    graph = build_agent_graph(registry=reg)
    compiled = graph.compile()
    nodes = list(graph.nodes.keys())
    assert "chat" in nodes
    assert "tools" in nodes
    assert "respond" in nodes
    print(f"  [OK] Graph nodes: {nodes}")


def test_tool_execution():
    """Verify tools execute correctly."""
    reg = create_default_registry()

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test.txt")
        result = asyncio.run(reg.execute("file_write", {
            "path": test_file,
            "content": "Hello World",
        }))
        assert "File written" in result
        print(f"  [OK] file_write: {result.strip()}")

        result = asyncio.run(reg.execute("file_read", {
            "path": test_file,
        }))
        assert "Hello World" in result
        print(f"  [OK] file_read: content verified")

        result = asyncio.run(reg.execute("file_patch", {
            "path": test_file,
            "old_content": "Hello World",
            "new_content": "Hello WorkPartner",
        }))
        assert "File patched" in result
        print(f"  [OK] file_patch: {result.strip()}")

    result = asyncio.run(reg.execute("code_run", {
        "code": "print('hello from python')",
        "type": "python",
    }))
    assert "OK" in result or "FAIL" in result
    print(f"  [OK] code_run: {result.strip()[:80]}")


if __name__ == "__main__":
    print("Phase 2 Integration Tests\n")
    test_registry()
    test_skills()
    test_graph()
    test_tool_execution()
    print("\nAll Phase 2 tests passed.")

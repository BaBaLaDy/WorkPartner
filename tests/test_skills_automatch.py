"""Test the OpenClaw-style skill system: XML metadata + explicit triggers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.skills.loader import SkillLoader
from src.skills.injector import SkillInjector, _explicit_mention


def test_xml_format():
    """Verify L1 output is XML format with name, description, location."""
    loader = SkillLoader(Path(__file__).parent.parent / "skills")
    loader.load_all()

    injector = SkillInjector(loader)
    prompt = injector.build_skills_prompt()

    # XML structure checks
    assert "<available_skills>" in prompt, "Missing XML root"
    assert "</available_skills>" in prompt, "Missing XML close"
    assert "<name>" in prompt, "Missing name tag"
    assert "<description>" in prompt, "Missing description tag"
    assert "<location>skills/" in prompt, "Missing location tag"

    print("[PASS] XML format: correct")
    print(f"  Prompt size: {len(prompt)} chars (should be small - metadata only)")


def test_explicit_mention_only():
    """Verify that only explicit mentions trigger injection, not keywords.

    Uses the bundled 'example' sample skill (skills/example/)."""
    loader = SkillLoader(Path(__file__).parent.parent / "skills")
    loader.load_all()
    injector = SkillInjector(loader)

    # Explicit mentions -> SHOULD inject
    assert injector.match_and_inject("请用example这个skill来演示一下")
    print("[PASS] Explicit: '请用example这个skill来演示' -> matched (injected)")

    injector.reset_session()

    assert injector.match_and_inject("use the example skill to show me")
    print("[PASS] Explicit: 'use the example skill' -> matched (injected)")

    injector.reset_session()

    assert injector.match_and_inject("/example help me with this")
    print("[PASS] Explicit: '/example help me' -> matched (injected)")

    injector.reset_session()

    # Keyword matches (no explicit mention) -> should NOT inject
    # These rely on the model reading the SKILL.md on its own
    assert not injector.match_and_inject("给我一个使用示例")
    print("[PASS] Keyword only: '给我一个使用示例' -> NOT injected (model decides)")

    assert not injector.match_and_inject("show me a sample of the report")
    print("[PASS] Keyword only: 'sample of the report' -> NOT injected (model decides)")

    assert not injector.match_and_inject("今天天气怎么样")
    print("[PASS] Unrelated: '今天天气怎么样' -> NOT injected")



def test_explicit_mention_helper():
    """Test the _explicit_mention helper directly."""
    # Should match
    assert _explicit_mention("pdf", "use the pdf skill to help me")
    assert _explicit_mention("pdf", "请用pdf这个skill来读取")
    assert _explicit_mention("pdf", "/pdf merge files")
    assert _explicit_mention("pdf", "can you use pdf skill to read this")
    assert _explicit_mention("pdf", "用pdf技能读取这个文件")

    # Should NOT match (these rely on model-driven loading)
    assert not _explicit_mention("pdf", "help me read this PDF file")
    assert not _explicit_mention("pdf", "合并这些pdf文件")
    assert not _explicit_mention("pdf", "extract text from the document")
    assert not _explicit_mention("xlsx", "help me with the pdf")

    print("[PASS] _explicit_mention: all cases correct")


def test_loaded_tracking():
    """Verify that once a skill is loaded, it won't be injected again."""
    loader = SkillLoader(Path(__file__).parent.parent / "skills")
    loader.load_all()
    injector = SkillInjector(loader)

    # First time: should match
    result = injector.match_and_inject("use the example skill")
    assert result, "First mention should match"

    # Second time: same skill already loaded, should skip
    result2 = injector.match_and_inject("use the example skill again")
    assert not result2, "Second mention should skip (already loaded)"

    print("[PASS] Loaded tracking: dedup works")


if __name__ == "__main__":
    print("OpenClaw-Style Skill System Tests\n")
    test_xml_format()
    test_explicit_mention_only()
    test_explicit_mention_helper()
    test_loaded_tracking()
    print("\nAll tests passed.")

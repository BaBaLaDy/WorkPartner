"""Unit tests for the lightweight tool contract layer."""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tools.registry import ToolRegistry


def test_register_preserves_plain_function_api():
    reg = ToolRegistry()

    def hello(name: str) -> str:
        """Say hello.

        Args:
            name: Name to greet.
        """
        return f"hello {name}"

    reg.register(hello, read_only=True, tags=("test",))

    assert reg.get("hello") is hello
    assert reg.list_names() == ["hello"]
    spec = reg.get_spec("hello")
    assert spec is not None
    assert spec.read_only is True
    assert spec.tags == ("test",)

    result = asyncio.run(reg.execute("hello", {"name": "Alice"}))
    assert result == "hello Alice"


def test_execute_result_exposes_metadata_and_permission_denials():
    reg = ToolRegistry()

    def delete_item(item_id: str) -> str:
        """Delete an item."""
        return f"deleted {item_id}"

    reg.register(
        delete_item,
        read_only=False,
        destructive=True,
        requires_permission=True,
    )

    def checker(spec, args):
        assert spec.name == "delete_item"
        assert args["item_id"] == "42"
        return "plan mode cannot mutate state"

    reg.set_permission_checker(checker)
    result = asyncio.run(
        reg.execute_result(
            "delete_item",
            {"item_id": "42"},
        )
    )

    assert result.success is False
    assert result.error == "permission_denied"
    assert "plan mode" in result.content


def test_ctx_excluded_from_llm_schema():
    """Verify that a `ctx` parameter is not exposed in the LLM tool schema."""
    reg = ToolRegistry()

    def current_session(query: str, ctx: object = None) -> str:
        """Return current session.

        Args:
            query: Query text.
        """
        return f"query={query}"

    reg.register(current_session)

    schema = reg.as_openai_tools()[0]["function"]
    assert "query" in schema["parameters"]["properties"]
    assert "ctx" not in schema["parameters"]["properties"]

    result = asyncio.run(
        reg.execute(
            "current_session",
            {"query": "session"},
        )
    )
    assert result == "query=session"


if __name__ == "__main__":
    test_register_preserves_plain_function_api()
    test_execute_result_exposes_metadata_and_permission_denials()
    test_ctx_excluded_from_llm_schema()
    print("Tool contract tests passed.")

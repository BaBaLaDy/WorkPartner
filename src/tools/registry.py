"""Tool registry: manages tool contracts, schemas, and implementations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ToolSpec:
    """Declarative contract for a tool.

    The function remains the implementation. The extra fields describe system
    semantics that are hard to infer from a Python signature: side effects,
    permission needs, concurrency expectations, and result size limits.
    """

    name: str
    fn: Callable[..., Any]
    description: str = ""
    read_only: bool = True
    destructive: bool = False
    requires_permission: bool = False
    concurrency_safe: bool = True
    max_result_chars: int = 0
    tags: tuple[str, ...] = ()
    schema: dict[str, Any] | None = None

    @property
    def mutates_state(self) -> bool:
        return not self.read_only


@dataclass(frozen=True)
class ToolResult:
    """Structured result from a tool execution.

    ``ToolRegistry.execute`` still returns a plain string for compatibility.
    Newer call sites can use ``execute_result`` when they need structured
    status, error type, or metadata.
    """

    tool_name: str
    content: str
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.content


PermissionChecker = Callable[[ToolSpec, dict[str, Any]], bool | str | None]


class ToolRegistry:
    """Registry for agent tools.

    Tools are still plain functions. ``ToolSpec`` adds a thin contract layer so
    the runtime can reason about side effects, permissions, concurrency, and
    result size without burying those rules in prompts or tool docstrings.
    """

    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}
        self._shutdown_cb: Callable | None = None
        self._permission_checker: PermissionChecker | None = None

    def set_shutdown_callback(self, cb: Callable) -> None:
        """Register a callback invoked when shutdown_agent tool is called."""
        self._shutdown_cb = cb

    def set_permission_checker(self, checker: PermissionChecker | None) -> None:
        """Register an optional permission gate invoked before tool execution.

        The default behavior remains permissive. A checker can return:
        - ``None`` or ``True`` to allow execution
        - ``False`` to deny with a generic message
        - a non-empty string to deny with that reason
        """
        self._permission_checker = checker

    def register(
        self,
        fn: Callable | None = None,
        *,
        name: str | None = None,
        read_only: bool = True,
        destructive: bool = False,
        requires_permission: bool = False,
        concurrency_safe: bool = True,
        max_result_chars: int = 0,
        tags: tuple[str, ...] | list[str] = (),
        schema: dict[str, Any] | None = None,
    ) -> Callable:
        """Register a tool function with optional contract metadata.

        Backwards compatible forms:

        ``reg.register(file_read)``
        ``@reg.register``

        Contract form:

        ``reg.register(file_write, read_only=False, requires_permission=True)``
        """
        if fn is None:
            return lambda real_fn: self.register(
                real_fn,
                name=name,
                read_only=read_only,
                destructive=destructive,
                requires_permission=requires_permission,
                concurrency_safe=concurrency_safe,
                max_result_chars=max_result_chars,
                tags=tags,
                schema=schema,
            )

        tool_name = name or fn.__name__
        spec = ToolSpec(
            name=tool_name,
            fn=fn,
            description=_function_description(fn),
            read_only=read_only,
            destructive=destructive,
            requires_permission=requires_permission,
            concurrency_safe=concurrency_safe,
            max_result_chars=max_result_chars,
            tags=tuple(tags),
            schema=schema,
        )
        self._tools[tool_name] = spec
        return fn

    def unregister(self, name: str) -> bool:
        """Remove a tool by name. Returns True if the tool existed and was removed."""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def register_with_schema(self, fn: Callable, schema: dict) -> Callable:
        """Register a tool with a pre-built OpenAI-compatible schema."""
        fn.__tool_schema__ = schema
        return self.register(fn, schema=schema)

    def get(self, name: str) -> Callable | None:
        spec = self._tools.get(name)
        return spec.fn if spec else None

    def get_spec(self, name: str) -> ToolSpec | None:
        """Return the full contract for a registered tool."""
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

    def list_specs(self) -> list[ToolSpec]:
        """Return all registered tool contracts."""
        return list(self._tools.values())

    def as_openai_tools(self) -> list[dict]:
        """Export all tools as OpenAI function-calling schemas."""
        schemas = []
        for spec in self._tools.values():
            schema = spec.schema or _function_to_openai_schema(spec.fn, name=spec.name)
            schemas.append({"type": "function", "function": schema})
        return schemas

    async def execute(self, name: str, args: dict) -> str:
        """Execute a tool by name and return the result as a string."""
        result = await self.execute_result(name, args)
        return result.content

    async def execute_result(
        self,
        name: str,
        args: dict | None,
    ) -> ToolResult:
        """Execute a tool by name and return structured execution metadata."""
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult(
                tool_name=name,
                content=f"Error: tool '{name}' not found. Available: {self.list_names()}",
                success=False,
                error="tool_not_found",
            )

        call_args = dict(args or {})

        denied = await self._permission_denial(spec, call_args)
        if denied:
            return ToolResult(
                tool_name=name,
                content=f"Permission denied for {name}: {denied}",
                success=False,
                error="permission_denied",
                metadata={"requires_permission": spec.requires_permission},
            )

        try:
            # Most tools are plain `def` functions (file/web/desktop/code_exec).
            # Calling them directly would block the event loop — and every
            # other concurrent coroutine (parallel SubAgents, other sessions)
            # — for the full duration of a network call or subprocess. Only
            # true `async def` tools are safe to await in-place; everything
            # else runs in a worker thread.
            if asyncio.iscoroutinefunction(spec.fn):
                result = await spec.fn(**call_args)
            else:
                result = await asyncio.to_thread(spec.fn, **call_args)
                if asyncio.iscoroutine(result):
                    result = await result

            content = _coerce_tool_content(result)
            content = _truncate_result(content, spec.max_result_chars)
            return ToolResult(
                tool_name=name,
                content=content,
                success=True,
                metadata={
                    "read_only": spec.read_only,
                    "destructive": spec.destructive,
                    "requires_permission": spec.requires_permission,
                },
            )
        except Exception as e:
            return ToolResult(
                tool_name=name,
                content=f"Error executing {name}: {e}",
                success=False,
                error=type(e).__name__,
            )

    async def _permission_denial(
        self,
        spec: ToolSpec,
        args: dict[str, Any],
    ) -> str | None:
        if self._permission_checker is None:
            return None

        decision = self._permission_checker(spec, args)

        if asyncio.iscoroutine(decision):
            decision = await decision

        if decision is False:
            return "blocked by permission checker"
        if isinstance(decision, str) and decision.strip():
            return decision.strip()
        return None


def _function_to_openai_schema(fn: Callable, *, name: str | None = None) -> dict:
    """Convert a type-hinted function to an OpenAI function schema.

    If the function has a ``__tool_schema_factory__`` or ``__tool_schema__``
    attribute, it is used instead of deriving the schema from signature/type
    hints. The factory form is useful when a schema depends on runtime config,
    such as the currently loaded role list.
    """
    if hasattr(fn, "__tool_schema_factory__"):
        schema = fn.__tool_schema_factory__()
        if name and schema.get("name") != name:
            schema = {**schema, "name": name}
        return schema

    # Allow tools to carry a pre-built schema (used by MCP tool wrappers)
    if hasattr(fn, "__tool_schema__"):
        schema = fn.__tool_schema__
        if name and schema.get("name") != name:
            schema = {**schema, "name": name}
        return schema

    from docstring_parser import parse
    import inspect
    from typing import get_type_hints

    sig = inspect.signature(fn)
    hints = get_type_hints(fn)

    # Use docstring-parser for robust Google/NumPy/reST docstring parsing
    doc = parse(fn.__doc__ or "")
    param_descriptions = {p.arg_name: p.description or "" for p in doc.params}

    properties = {}
    required = []
    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls", "ctx"):
            continue
        param_type = hints.get(param_name, str)
        json_type = _python_type_to_json(param_type)
        desc = param_descriptions.get(param_name, f"Parameter: {param_name}")
        properties[param_name] = {
            "type": json_type,
            "description": desc,
        }
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    # Extract description from docstring (short description)
    description = doc.short_description or ""

    schema = {
        "name": name or fn.__name__,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }
    return schema


def _function_description(fn: Callable) -> str:
    try:
        from docstring_parser import parse
        return parse(fn.__doc__ or "").short_description or ""
    except Exception:
        return ""


def _coerce_tool_content(result: Any) -> str:
    if isinstance(result, ToolResult):
        return result.content
    return str(result)


def _truncate_result(content: str, max_chars: int) -> str:
    if max_chars <= 0 or len(content) <= max_chars:
        return content
    head = max_chars * 2 // 3
    tail = max_chars - head
    return (
        content[:head]
        + f"\n...[tool result truncated to {max_chars} chars]...\n"
        + content[-tail:]
    )


def _python_type_to_json(py_type) -> str:
    origin = getattr(py_type, "__origin__", None)
    if origin is not None:
        # Handle Optional[X], List[X] etc.
        from typing import get_args
        args = get_args(py_type)
        if origin is list or origin is set:
            return "array"
        if len(args) > 0:
            return _python_type_to_json(args[0])
    mapping = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }
    return mapping.get(py_type, "string")

"""Shared agent session — init, system prompt, and streaming runner.

Used by CLI (main.py) and web API (src/api/). All agent logic lives here.
"""

import os
import platform
import re
from datetime import datetime
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

from src.providers.factory import create_model, load_config
from src.providers.model_router import ModelRouter
from src.tools.registry import ToolRegistry
from src.tools.defaults import create_default_registry
try:
    from src.tools.desktop import apply_desktop_config
    HAS_DESKTOP = True
except ImportError:
    HAS_DESKTOP = False
from src.mcp.manager import MCPManager
from src.roles.loader import Role, build_role_presence
from src.skills.loader import SkillLoader
from src.skills.injector import SkillInjector
from src.tasks.todo import TodoManager
from src.services.todo_service import TodoService
from .graph import create_agent
from .session_manager import SessionManager

# ---------------------------------------------------------------------------
# System prompt — single source of truth for both CLI and web UI
# ---------------------------------------------------------------------------
# Tool names / params are intentionally NOT listed here — bind_tools() sends
# the full JSON Schema to the model. This prompt only contains behavioral rules
# and workflows that schemas cannot express.

BASE_SYSTEM_PROMPT = """You are WorkPartner, a concise work assistant agent.

## Rules
- Be concise. Before irreversible tools (file_write, file_patch, code_run), briefly explain the action.
- If a tool fails, understand the error and try a different approach. Fail 3+ times → tell the user.
- Answer in the user's language.

## Decision Guide
When facing a task, classify it first:

| If the task has...              | Then...                    |
|--------------------------------|----------------------------|
| Need external / current info   | web_search, then web_extract to read details. Always cite sources. |
| Multiple independent parts     | Use ONE subagent_batch call with all independent tasks in its tasks array. Put the assignee in each tasks[i].role using a configured role id/display name from the tool schema. Never put a free-form role prompt into role. After results return, synthesize and deliver final answer. |
| User says "complete my tasks" / "开始托管" | todo_list(status="pending"), then execute ONE BY ONE, calling todo_update(id, status="done") after each. Report summary when done. |
| Desktop interaction needed     | desktop_locate() to find targets, then click → screenshot to verify. Never claim success without screenshot confirmation. |
| Simple question / chat         | Answer directly. |

## Skills
<available_skills> below lists installed skills. If exactly one matches the task, file_read its <location> first and follow its instructions exactly. Never load more than one skill up front. No match → answer normally."""


THINKING_PROTOCOL = """


## Thinking Protocol
Before every response, output reasoning inside `<thinking>...</thinking>` tags, then the actual response.

Example:
<thinking>
User wants to read config.yaml. I'll use file_read to get the contents first.
</thinking>
Let me read the config file for you.
"""


def _detect_conversation_mode(user_message: str) -> dict[str, str] | None:
    """Infer a lightweight session-local interaction mode from the latest user turn."""
    text = (user_message or "").strip().lower()
    if not text:
        return None

    rules = [
        (
            ("着急", "赶紧", "尽快", "马上", "asap", "urgent", "quickly", "right now"),
            {
                "mode": "rushed",
                "label": "Rushed",
                "guidance": (
                    "Keep the response short, front-load the answer, and avoid decorative phrasing. "
                    "When the work is large, propose the fastest safe next slice instead of a long plan."
                ),
            },
        ),
        (
            ("烦", "糟", "崩", "失败", "卡住", "火大", "annoyed", "frustrated", "stuck", "blocked"),
            {
                "mode": "frustrated",
                "label": "Frustrated",
                "guidance": (
                    "Acknowledge the blockage plainly, avoid sounding defensive, and focus on recovery steps. "
                    "Prefer concrete fixes over reassurance-only language."
                ),
            },
        ),
        (
            ("累", "疲惫", "没精神", "深夜", "困", "tired", "exhausted", "late", "sleepy"),
            {
                "mode": "low_energy",
                "label": "Low energy",
                "guidance": (
                    "Use low-friction wording, reduce cognitive load, and prefer direct execution or short options. "
                    "Avoid overloading the user with long branching explanations."
                ),
            },
        ),
        (
            ("不知道", "帮我想", "犹豫", "拿不准", "not sure", "help me think", "unsure"),
            {
                "mode": "exploratory",
                "label": "Exploratory",
                "guidance": (
                    "Slow down slightly, frame tradeoffs clearly, and help the user choose without pretending certainty. "
                    "Offer a recommendation with a brief rationale."
                ),
            },
        ),
        (
            ("谢谢", "辛苦", "不错", "太好了", "thanks", "great", "nice", "appreciate"),
            {
                "mode": "positive",
                "label": "Positive",
                "guidance": (
                    "Keep the tone warm but restrained. Reinforce momentum and move cleanly to the next useful action."
                ),
            },
        ),
    ]

    for keywords, mode in rules:
        if any(keyword in text for keyword in keywords):
            return mode
    return None


def _build_conversation_mode_prompt(user_message: str) -> str:
    mode = _detect_conversation_mode(user_message)
    if mode is None:
        return ""
    return (
        "## Conversation mode\n"
        f"- Current mode: {mode['label']}\n"
        f"- Guidance: {mode['guidance']}"
    )


def _build_runtime_context() -> str:
    """Single-line runtime context — minimal, under 150 chars."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tz = datetime.now().astimezone().strftime("%Z")
    return (
        f"<runtime>now={now} {tz} | "
        f"os={platform.system()} | "
        f"cwd={os.getcwd()}</runtime>"
    )


def build_system_prompt(injector: SkillInjector, user_message: str = "",
                        memory_manager: Any = None, role: Role | None = None) -> str:
    """Build the full system prompt for a turn.

    Delegates to PromptAssembler for cache-aware section ordering.
    """
    from src.agent.prompt import PromptAssembler
    assembler = PromptAssembler()
    return assembler.assemble(
        profile="interactive",
        role=role,
        base_rules=BASE_SYSTEM_PROMPT + THINKING_PROTOCOL,
        injector=injector,
        user_message=user_message,
        memory_manager=memory_manager,
    )


# ---------------------------------------------------------------------------
# AgentSession — wires up everything from config.yaml
# ---------------------------------------------------------------------------
class AgentSession:
    """Holds all initialised objects for an agent session.

    Persistence: uses SessionManager which wraps a SqliteSaver.
    Conversations survive process restarts automatically.
    """

    def __init__(self, session_manager: SessionManager | None = None,
                 todo_service: TodoService | None = None,
                 session_type: str = "interactive",
                 owner: str = "cli",
                 workspace_scope: str = "",
                 permission_mode: str = "operate",
                 model_router: ModelRouter | None = None,
                 role: Role | None = None,
                 memory_manager: Any = None,
                 # External shared components (optional — when Engine manages)
                 agent: Any = None,
                 registry: ToolRegistry | None = None,
                 tool_schemas: list[dict] | None = None,
                 injector: Any = None):
        self.role = role
        config = load_config()

        # -- session persistence --
        if session_manager is None:
            history_dir = config.get("history", {}).get("directory", "./history")
            session_manager = SessionManager(history_dir)
        self.sessions = session_manager

        # -- provider / model --
        if model_router is not None:
            self.model_router = model_router
            self.model: ChatOpenAI = model_router.get_model("chat")
        else:
            self.model_router = None
            self.model: ChatOpenAI = create_model()

        # -- tools --
        if registry is not None:
            # Use externally provided registry and schemas
            self.registry: ToolRegistry = registry
            self.tool_schemas = tool_schemas if tool_schemas is not None else registry.as_openai_tools()
        else:
            self.registry: ToolRegistry = create_default_registry()
            # Interactive sessions do not get SubAgent tools.
            self.tool_schemas = self.registry.as_openai_tools()

        # -- MCP --
        if agent is None:
            mcp_cfg = config.get("mcp", {})
            history_dir = config.get("history", {}).get("directory", "./history")
            self.mcp = MCPManager(
                self.registry,
                history_dir=history_dir,
                tool_prefix=mcp_cfg.get("tool_prefix", "mcp"),
            )
            self._mcp_auto_connect = mcp_cfg.get("auto_connect", True)
        else:
            self.mcp = None
            self._mcp_auto_connect = False

        # -- desktop config (Windows-only) --
        if agent is None and HAS_DESKTOP:
            desktop_cfg = config.get("desktop", {})
            if desktop_cfg:
                apply_desktop_config(desktop_cfg)

        # -- skills --
        if injector is not None:
            # Use externally provided skill injector
            self.loader = None
            self.injector = injector
        elif agent is None:
            skills_dir = config.get("skills", {}).get("directory", "./skills")
            self.loader = SkillLoader(skills_dir)
            self.loader.load_all()
            self.injector = SkillInjector(self.loader)
        else:
            self.loader = None
            self.injector = None

        # -- agent graph --
        if agent is not None:
            # Use externally provided shared graph
            self.agent = agent
            max_turns = config.get("agent", {}).get("max_turns", 70)
            self.thread = {
                **self.sessions.thread_config(),
                "recursion_limit": max_turns,
            }
        else:
            agent_cfg = config.get("agent", {})
            compression_threshold = agent_cfg.get("compression_threshold", 30)
            compression_keep_recent = agent_cfg.get("compression_keep_recent", 5)
            max_turns = agent_cfg.get("max_turns", 70)

            self.agent = create_agent(
                model=self.model,
                registry=self.registry,
                checkpointer=self.sessions.checkpointer,
                compression_threshold=compression_threshold,
                compression_keep_recent=compression_keep_recent,
                summary_model=self.model_router.get_model("utility_large") if self.model_router else None,
            )

            self.thread = {
                **self.sessions.thread_config(),
                "recursion_limit": max_turns,
            }

        # -- todolist --
        if todo_service is not None:
            self.todo = todo_service
        else:
            tasks_file = config.get("tasks", {}).get("file", "./tasks.json")
            self.todo = TodoManager(tasks_file)

        # -- thinking parser state --
        self._in_thinking = False
        self._turn = 0

        # -- session metadata (Phase 2) --
        self._session_type = session_type
        self._owner = owner
        self._workspace_scope = workspace_scope
        self._permission_mode = permission_mode

        # -- memory --
        self._memory_manager = memory_manager

    def load_history(self) -> list[dict]:
        """Load previous conversation messages for UI display.

        Returns a list of {"role": "user"|"assistant", "content": str} dicts.
        """
        try:
            snapshot = self.agent.get_state(self.thread)
            if snapshot is None or not snapshot.values:
                return []
            messages = snapshot.values.get("messages", [])
        except Exception:
            return []

        result = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                result.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage) and msg.content:
                result.append({"role": "assistant", "content": msg.content})
        return result

    async def start_mcp(self) -> None:
        """Start MCP manager and auto-connect enabled servers.

        Must be called after __init__ since it is async.
        No-op when MCP manager is externally provided (Engine-managed).
        """
        if self.mcp is not None and self._mcp_auto_connect:
            await self.mcp.start()

    async def stop_mcp(self) -> None:
        """Shut down all MCP connections. Call during session teardown.

        No-op when MCP manager is externally provided (Engine-managed).
        """
        if self.mcp is not None:
            await self.mcp.stop()

    def _get_messages(self) -> list:
        """Get raw LangChain messages from the session (for memory summarization).

        If the state has a compression_summary (context was compacted), prepends
        a synthetic SystemMessage so summarize_session sees the full history.
        """
        try:
            snapshot = self.agent.get_state(self.thread)
            if snapshot is None or not snapshot.values:
                return []
            messages = list(snapshot.values.get("messages", []))
            compression_summary = snapshot.values.get("compression_summary")
            if compression_summary:
                from langchain_core.messages import SystemMessage
                messages = [
                    SystemMessage(content=f"[Earlier context]\n{compression_summary}")
                ] + messages
            return messages
        except Exception:
            return []

    def auto_title(self, user_message: str) -> str | None:
        """Generate a session title from the first user message.

        Returns None if the session already has a meaningful title.
        Only auto-titles placeholder names matching 'Session YYYY-MM-DD #N'.
        """
        info = self.sessions.get_session(self.sessions.active_id)
        if info is None:
            return None
        name = info.get("name", "")
        # Only auto-title if name is a placeholder (e.g., "Session 2026-05-04 #1")
        import re
        if not re.match(r"^Session \d{4}-\d{2}-\d{2} #\d+$", name):
            return None
        # Truncate to 40 chars, break at word boundary if possible
        clean = user_message.strip().replace("\n", " ")
        if len(clean) > 40:
            clean = clean[:37] + "..."
        return clean

    def maybe_auto_title(self, user_message: str):
        """Check and apply auto-title after the first user message."""
        title = self.auto_title(user_message)
        if title:
            self.sessions.update_title(self.sessions.active_id, title)

    def task_done(self, task_id: str):
        """Mark a task as done, recording the current session."""
        self.todo.mark_done(task_id, session_id=self.sessions.active_id)

    def task_add(self, title: str, description: str = "", priority: str = "medium") -> dict:
        """Add a task, recording the current session."""
        return self.todo.add(title, description, priority, session_id=self.sessions.active_id)

    def sync_thread(self):
        """Update thread config from session manager (call after session switch)."""
        self.thread = {
            **self.sessions.thread_config(),
            "recursion_limit": self.thread["recursion_limit"],
        }

    def reset_agent(self):
        """Rebuild the agent graph with current settings (preserves thread history).

        When using a shared graph (Engine-managed), this is a no-op —
        use engine-level reset instead. MCP connections are NOT affected.
        """
        if self.mcp is None:
            # Shared graph — don't reset locally
            return

        config = load_config()
        agent_cfg = config.get("agent", {})
        compression_threshold = agent_cfg.get("compression_threshold", 30)
        compression_keep_recent = agent_cfg.get("compression_keep_recent", 5)
        max_turns = agent_cfg.get("max_turns", 70)

        self.agent = create_agent(
            model=self.model,
            registry=self.registry,
            checkpointer=self.sessions.checkpointer,
            compression_threshold=compression_threshold,
            compression_keep_recent=compression_keep_recent,
            summary_model=self.model_router.get_model("utility_large") if self.model_router else None,
        )
        self.thread = {
            **self.sessions.thread_config(),
            "recursion_limit": max_turns,
        }

    def _parse_thinking(self, text: str) -> list[tuple[str, str]]:
        """Parse streaming text for <thinking> tags.

        Returns list of ("thinking_delta"|"text_delta", content) tuples.
        Uses a buffer to handle tags that span across multiple chunks.
        """
        if not hasattr(self, '_think_buf'):
            self._think_buf = ""
        self._think_buf += text

        events: list[tuple[str, str]] = []
        remaining = self._think_buf
        consumed = 0
        n = len(remaining)

        while consumed < n:
            remaining = self._think_buf[consumed:]
            if not self._in_thinking:
                m = re.search(r'<think(?:ing)?>', remaining)
                if m:
                    if m.start() > 0:
                        events.append(("text_delta", remaining[:m.start()]))
                    consumed += m.end()
                    self._in_thinking = True
                else:
                    # Check for partial opening tag at end
                    partials = ['<', '<t', '<th', '<thi', '<thin', '<think', '<thinki', '<thinkin', '<thinking']
                    tail = remaining
                    if any(tail.endswith(p) for p in partials) and len(tail) < 20:
                        break  # keep in buffer, wait for more
                    if tail:
                        events.append(("text_delta", tail))
                    consumed += len(tail)
            else:
                m = re.search(r'</think(?:ing)?>', remaining)
                if m:
                    if m.start() > 0:
                        events.append(("thinking_delta", remaining[:m.start()]))
                    consumed += m.end()
                    self._in_thinking = False
                else:
                    # Check for partial closing tag at end
                    partials = ['<', '</', '</t', '</th', '</thi', '</thin', '</think', '</thinki', '</thinkin', '</thinking']
                    tail = remaining
                    if any(tail.endswith(p) for p in partials) and len(tail) < 20:
                        break  # keep in buffer, wait for more
                    if tail:
                        events.append(("thinking_delta", tail))
                    consumed += len(tail)

        self._think_buf = self._think_buf[consumed:]
        return events

    async def stream_events(
        self, user_message: str, system_prompt: str,
        thread_id: str | None = None,
    ) -> AsyncIterator[dict]:
        """Run the agent and yield display events.

        Emits both original LangGraph events (for backward compat) and new
        semantic events: turn_start, thinking_delta, text_delta, tool_input, tool_output.

        If thread_id is given, uses that thread config instead of the
        session's default — used by IM bridge for per-chat routing.
        """
        self._in_thinking = False
        self._think_buf = ""
        self._turn = 0

        thread_config = (
            {**self.sessions.thread_config(thread_id), "recursion_limit": self.thread["recursion_limit"]}
            if thread_id else self.thread
        )

        stream = self.agent.astream_events(
            {
                "messages": [HumanMessage(content=user_message)],
                "system_prompt": system_prompt,
                "tools": self.tool_schemas,
                "compression_summary": None,
                "session_type": self._session_type,
                "owner": self._owner,
                "workspace_scope": self._workspace_scope,
                "permission_mode": self._permission_mode,
                "task_id": None,
                "parent_schedule_id": None,
                "run_status": "running",
                "failure_count": 0,
                "last_tool_summary": "",
            },
            config=thread_config,
            version="v2",
        )

        try:
            async for event in stream:
                kind = event.get("event", "")

                if kind == "on_chat_model_start":
                    self._turn += 1
                    yield {"event": "turn_start", "data": {"turn": self._turn}}

                elif kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    content = chunk.content or ""
                    if content:
                        for evt_type, text in self._parse_thinking(content):
                            if text:
                                yield {"event": evt_type, "data": text}
                    yield event

                elif kind == "on_chat_model_end":
                    if self._in_thinking:
                        self._in_thinking = False

                    output = event.get("data", {}).get("output", {})
                    for tc in getattr(output, "tool_calls", None) or []:
                        name = tc.get("name", "")
                        args = tc.get("args", {})
                        yield {
                            "event": "tool_input",
                            "data": {"name": name, "input": args},
                        }
                    yield event

                elif kind == "on_chain_end" and event.get("name") == "tools":
                    output = event.get("data", {}).get("output", {})
                    for msg in output.get("messages", []):
                        if hasattr(msg, "content") and hasattr(msg, "name"):
                            yield {
                                "event": "tool_output",
                                "data": {
                                    "name": msg.name or "",
                                    "output": str(msg.content),
                                },
                            }
                    yield event

                elif kind in ("on_tool_start", "on_tool_end"):
                    pass

                else:
                    yield event
        finally:
            if thread_id:
                self.sessions.touch(thread_id)
            else:
                self.sessions.touch()

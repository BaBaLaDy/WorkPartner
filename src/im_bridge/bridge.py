"""BridgeManager — central orchestrator for IM platform adapters.

Owns the AgentSession, manages adapter lifecycle, and provides
per-chat thread routing for the LangGraph agent.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage

from src.agent.session import build_system_prompt as _build_default_prompt
from src.agent.session_manager import SessionManager
from src.providers.factory import load_config

from src.agent.display import fmt_tool_input, fmt_tool_output, print_thinking

if TYPE_CHECKING:
    from src.agent.session import AgentSession

logger = logging.getLogger(__name__)

IM_THREAD_PREFIX = "im"
BRIDGE_SESSIONS_FILE = Path("history/bridge_sessions.json")


def _sanitize_thread_name(name: str) -> str:
    """Turn a platform:chat_id key into a safe thread name."""
    safe = "".join(
        ch for ch in name
        if ch.isalnum() or ch in ("-", "_", ":")
    )
    return safe[:80]


class BridgeManager:
    """Manages IM adapter lifecycle and routes messages to the agent.

    Usage::

        bridge = BridgeManager()
        await bridge.start()   # creates AgentSession + starts adapters
        # ... messages flow ...
        await bridge.stop()
    """

    def __init__(self, config: dict | None = None):
        self._config = config or load_config()
        self._adapters: dict[str, "BaseAdapter"] = {}
        self._agent_session: "AgentSession | None" = None
        self._running = False
        self._started = False
        self._bridge_sessions: dict[str, dict] = self._load_bridge_sessions()

        # Store adapter configs for per-adapter lifecycle
        bridge_cfg = self._config.get("im_bridge", {})
        self._adapters_config: dict[str, dict] = bridge_cfg.get("adapters", {})

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def agent_session(self) -> "AgentSession":
        if self._agent_session is None:
            raise RuntimeError("BridgeManager not started — call start() first")
        return self._agent_session

    @property
    def running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Bridge session persistence
    # ------------------------------------------------------------------

    def _load_bridge_sessions(self) -> dict:
        """Load bridge session mapping from bridge_sessions.json."""
        if BRIDGE_SESSIONS_FILE.exists():
            try:
                return json.loads(BRIDGE_SESSIONS_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, KeyError):
                pass
        return {}

    def _save_bridge_sessions(self):
        """Persist bridge session mapping to disk."""
        BRIDGE_SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        BRIDGE_SESSIONS_FILE.write_text(
            json.dumps(self._bridge_sessions, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, agent_session: "AgentSession | None" = None) -> bool:
        """Start the bridge and all configured adapters.

        Pass an existing AgentSession to share with CLI or the Web UI,
        or let the bridge create its own.
        """
        if self._started:
            logger.warning("BridgeManager already started")
            return True

        # Create or use provided agent session
        if agent_session is not None:
            self._agent_session = agent_session
        else:
            from src.agent.session import AgentSession
            self._agent_session = AgentSession()

        # Connect all enabled adapters
        bridge_cfg = self._config.get("im_bridge", {})
        adapters_cfg = bridge_cfg.get("adapters", {})

        if not adapters_cfg:
            logger.warning("No IM adapters configured in config.yaml → im_bridge.adapters")
            self._started = True
            self._running = True
            return True

        connected_count = 0
        for name, adapter_cfg in adapters_cfg.items():
            if not adapter_cfg.get("enabled", True):
                logger.info("Adapter '%s' disabled, skipping", name)
                continue
            if await self.connect_adapter(name, adapter_cfg):
                connected_count += 1

        self._started = True
        self._running = True
        logger.info("BridgeManager started — %d adapter(s) connected", connected_count)
        return connected_count > 0

    async def stop(self) -> None:
        """Stop all adapters and clean up."""
        self._running = False

        for name in list(self._adapters.keys()):
            await self.disconnect_adapter(name)

        self._started = False
        logger.info("BridgeManager stopped")

    # ------------------------------------------------------------------
    # Per-adapter lifecycle
    # ------------------------------------------------------------------

    async def connect_adapter(self, name: str, cfg: dict | None = None) -> bool:
        """Connect a single adapter by name.

        If cfg is not provided, reads from stored adapter config.
        """
        if name in self._adapters:
            logger.warning("[%s] Already connected", name)
            return True

        if cfg is None:
            cfg = self._adapters_config.get(name, {})
            if not cfg:
                logger.error("[%s] No config available for adapter", name)
                return False

        # Ensure agent session exists
        if self._agent_session is None:
            from src.agent.session import AgentSession
            self._agent_session = AgentSession()

        adapter = self._create_adapter(name, cfg)
        if adapter is None:
            return False

        try:
            result = await adapter.connect()
        except Exception as e:
            logger.error("[%s] Failed to connect: %s", name, e)
            return False

        if result:
            self._adapters[name] = adapter
            self._running = True
            self._started = True
            logger.info("[%s] Connected successfully", name)
        return result

    async def disconnect_adapter(self, name: str) -> bool:
        """Disconnect a single adapter by name."""
        adapter = self._adapters.pop(name, None)
        if adapter is None:
            return False
        try:
            await adapter.disconnect()
            logger.info("[%s] Disconnected", name)
        except Exception:
            logger.exception("[%s] Error during disconnect", name)

        # Update running state
        if not self._adapters:
            self._running = False
        return True

    def list_adapters(self) -> list[dict]:
        """Return status of all configured adapters."""
        result = []
        for name, cfg in self._adapters_config.items():
            result.append({
                "name": name,
                "enabled": cfg.get("enabled", False),
                "connected": name in self._adapters,
                "display_name": cfg.get("display_name", name),
            })
        # Also include any dynamically connected adapters not in config
        for name in self._adapters:
            if name not in self._adapters_config:
                result.append({
                    "name": name,
                    "enabled": True,
                    "connected": True,
                    "display_name": name,
                })
        return result

    def _create_adapter(self, name: str, cfg: dict):
        """Create an adapter instance by name.

        Maps config key names like 'telegram', 'feishu' to adapter classes.
        """
        if name == "telegram":
            from .adapters.telegram import TelegramAdapter
            return TelegramAdapter(cfg, self)
        elif name == "feishu" or name == "lark":
            from .adapters.feishu import FeishuAdapter
            return FeishuAdapter(cfg, self)
        else:
            logger.error("Unknown adapter type: '%s'", name)
            return None

    # ------------------------------------------------------------------
    # Thread / session routing
    # ------------------------------------------------------------------

    def get_or_create_thread(self, session_key: str, display_name: str = "") -> str:
        """Get or create a LangGraph thread for an IM chat.

        Each IM chat (platform:chat_id) maps to a persistent LangGraph thread,
        giving it its own conversation history, checkpoint, and context.
        Uses precise dict lookup from bridge_sessions.json (O(1)).
        Does NOT modify the global active session pointer.
        """
        from datetime import datetime, timezone

        entry = self._bridge_sessions.get(session_key)
        if entry is not None:
            thread_id = entry["thread_id"]
            # Touch last_active
            entry["last_active"] = datetime.now(timezone.utc).isoformat()
            self._save_bridge_sessions()
            return thread_id

        # Create new thread via SessionManager (does not change active_id)
        sm = self.agent_session.sessions
        # display_name comes from the IM platform (attacker-controlled) —
        # sanitize it before persisting.
        safe_display = _sanitize_thread_name(display_name) if display_name else ""
        name = f"{session_key}" if not safe_display else f"{session_key} ({safe_display})"
        thread_id = sm.create_session(name)

        # Determine platform from session_key
        platform = session_key.split(":")[0] if ":" in session_key else "unknown"

        # Store mapping with Phase 2 metadata
        self._bridge_sessions[session_key] = {
            "thread_id": thread_id,
            "session_key": session_key,
            "display_name": safe_display,
            "platform": platform,
            "session_type": "bridge",
            "owner": platform,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_active": datetime.now(timezone.utc).isoformat(),
        }
        self._save_bridge_sessions()
        logger.info("Created thread %s for IM chat %s", thread_id, session_key)
        return thread_id

    # ------------------------------------------------------------------
    # Agent runner
    # ------------------------------------------------------------------

    async def run_agent(
        self,
        thread_id: str,
        user_message: str,
        system_prompt: str,
    ) -> str:
        """Run the WorkPartner agent for an IM message and collect the response.

        Uses LangGraph streaming — collects text_delta events into the
        final response, and prints thinking/tool calls to console.
        """
        session = self.agent_session

        # Build the full system prompt (skills + runtime + IM context)
        full_prompt = _build_default_prompt(session.injector, user_message)
        full_prompt += "\n\n[IM Context]\n" + system_prompt

        # Collect response pieces
        response_parts: list[str] = []
        thinking_buf = False

        try:
            async for event in session.stream_events(
                user_message, full_prompt, thread_id=thread_id,
            ):
                kind = event.get("event", "")
                if kind == "text_delta":
                    text = str(event["data"])
                    response_parts.append(text)
                    # If we were in thinking mode, close it first
                    if thinking_buf:
                        thinking_buf = False
                    print(text, end="", flush=True)

                elif kind == "thinking_delta":
                    thinking_buf = True
                    print_thinking(event["data"])

                elif kind == "turn_start":
                    turn = event["data"]["turn"]
                    print(f"\n{'─' * 25} Turn {turn} {'─' * 25}")

                elif kind == "tool_input":
                    # Close thinking mode if active
                    if thinking_buf:
                        thinking_buf = False
                    info = event["data"]
                    print(fmt_tool_input(info["name"], info["input"]))

                elif kind == "tool_output":
                    print(fmt_tool_output(event["data"]["output"]))

                elif kind == "on_chain_start" and event.get("name") == "compress":
                    print("\n[Compressing context...] ", end="", flush=True)

                elif kind == "on_chain_end" and event.get("name") == "compress":
                    summary = event.get("data", {}).get("output", {}).get("compression_summary", "")
                    print(f"done ({len(summary)} chars)", flush=True)

        except asyncio.CancelledError:
            logger.warning("Agent run cancelled for thread %s", thread_id)
            return "".join(response_parts) if response_parts else ""
        except Exception:
            logger.exception("Agent run error for thread %s", thread_id)
            raise

        return "".join(response_parts)

    async def run_agent_simple(
        self,
        thread_id: str,
        user_message: str,
        system_prompt: str = "",
    ) -> str:
        """Non-streaming agent run — invokes the graph directly.

        Faster for simple cases where streaming isn't needed.
        """
        session = self.agent_session

        thread_config = {
            **session.sessions.thread_config(thread_id),
            "recursion_limit": session.thread.get("recursion_limit", 70),
        }

        full_prompt = _build_default_prompt(session.injector, user_message)
        if system_prompt:
            full_prompt += "\n\n[IM Context]\n" + system_prompt

        from langchain_core.messages import AIMessage

        thread_config = {
            **session.sessions.thread_config(thread_id),
            "recursion_limit": session.thread.get("recursion_limit", 70),
        }

        result = await session.agent.ainvoke(
            {
                "messages": [HumanMessage(content=user_message)],
                "system_prompt": full_prompt,
                "tools": session.tool_schemas,
                "compression_summary": None,
            },
            config=thread_config,
        )

        session.sessions.touch(thread_id)

        messages = result.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                return str(msg.content)
        return ""

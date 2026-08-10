"""Base adapter class for IM platform integrations.

Each platform adapter (Telegram, Feishu, etc.) inherits from this and
implements platform-specific connection, receive, and send logic.

The base class handles:
- Message deduplication
- Serial per-chat processing (no overlapping agent turns)
- Routing messages to the WorkPartner LangGraph agent
- Building platform-aware system prompts
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from .message import IMessage, SendResult, MessageDeduplicator

if TYPE_CHECKING:
    from .bridge import BridgeManager

logger = logging.getLogger(__name__)


class BaseAdapter(ABC):
    """Abstract platform adapter.

    Subclasses implement:
    - connect() → bool     establish connection, start receiving
    - disconnect()          tear down connection
    - send(chat_id, text) → SendResult
    """

    platform: str  # set by subclass: "telegram", "feishu", etc.
    MAX_MESSAGE_LENGTH = 4000

    def __init__(self, config: dict, bridge: "BridgeManager"):
        self.config = config
        self.bridge = bridge
        self._running = False
        self._dedup = MessageDeduplicator()
        # Serial processing: one agent turn per session at a time
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._active_locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def connect(self) -> bool:
        """Start the adapter — connect to platform, begin receiving messages.

        Returns True on success.
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Stop the adapter — close connections, cancel tasks."""
        ...

    @property
    def running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    @abstractmethod
    async def send(
        self,
        chat_id: str,
        content: str,
        *,
        reply_to: str | None = None,
        thread_id: str | None = None,
    ) -> SendResult:
        """Send a text message to the given chat.

        The adapter is responsible for:
        - Platform-specific formatting (Markdown dialect, escaping)
        - Splitting long messages to fit platform limits
        - Handling reply threading
        """
        ...

    async def send_typing(self, chat_id: str) -> None:
        """Signal typing indicator. Override if platform supports it."""
        pass

    # ------------------------------------------------------------------
    # Inbound → Agent routing
    # ------------------------------------------------------------------

    async def handle_message(self, msg: IMessage) -> str | None:
        """Process an inbound message through the WorkPartner agent.

        Returns the agent's text response, or None if nothing to send.
        """
        # Dedup
        if self._dedup.is_duplicate(msg.message_id):
            logger.debug("[%s] Duplicate message %s ignored", self.platform, msg.message_id)
            return None

        # Serial processing per session
        lock = self._active_locks.setdefault(msg.session_key, asyncio.Lock())

        async with lock:
            try:
                return await self._process_message(msg)
            except Exception:
                logger.exception("[%s] Error processing message from %s", self.platform, msg.user_id)
                return None

    async def _process_message(self, msg: IMessage) -> str | None:
        """Internal: route message to agent and collect response."""
        agent = self.bridge.agent_session

        # Get or create session for this IM chat
        thread_id = self.bridge.get_or_create_thread(msg.session_key, msg.user_name)

        # Build system prompt with IM context
        system_prompt = self._build_system_prompt(msg)

        # Build user message with reply context
        user_text = msg.content
        if msg.reply_to_text:
            user_text = (
                f'[引用回复 "{msg.reply_to_text[:200]}"]\n\n{user_text}'
            )

        # Run agent and collect response
        try:
            response = await self.bridge.run_agent(
                thread_id=thread_id,
                user_message=user_text,
                system_prompt=system_prompt,
            )
        except Exception:
            logger.exception("[%s] Agent run failed for %s", self.platform, msg.session_key)
            return "抱歉，处理你的消息时出错了。请稍后重试。"

        if not response or not response.strip():
            return None

        response = response.strip()

        # Send the response back to the IM platform
        result = await self.send(
            chat_id=msg.chat_id,
            content=response,
            reply_to=msg.reply_to,
        )
        if result and result.success:
            logger.info("[%s] Sent reply to %s (msg_id=%s)",
                        self.platform, msg.chat_id, result.message_id)
        else:
            error = result.error if result else "unknown"
            logger.warning("[%s] Failed to send reply to %s: %s",
                           self.platform, msg.chat_id, error)

        return response

    def _build_system_prompt(self, msg: IMessage) -> str:
        """Build system prompt with IM platform context."""
        parts = [
            f"You are WorkPartner, responding via {self.platform}.",
        ]
        if msg.chat_type == "group":
            parts.append(
                f"You are in a group chat. User {msg.user_name} sent a message. "
                "Be concise and address the group context."
            )
        else:
            parts.append(
                f"You are in a direct message with {msg.user_name}. "
                "Be helpful and conversational."
            )
        parts.append(
            f"Current platform: {self.platform}. "
            f"Chat ID: {msg.chat_id}. "
            f"User: {msg.user_name} ({msg.user_id})."
        )
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def split_text(text: str, max_len: int) -> list[str]:
        """Split text into chunks under max_len, trying to break at newlines."""
        if len(text) <= max_len:
            return [text]
        chunks = []
        while len(text) > max_len:
            # Try to split at the last newline within the limit
            split_at = text.rfind("\n", 0, max_len)
            if split_at == -1 or split_at < max_len // 2:
                split_at = max_len
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
        if text:
            chunks.append(text)
        return chunks

    def _coerce_list(self, value) -> list[str]:
        """Coerce config values into a trimmed string list."""
        if value is None:
            return []
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        if isinstance(value, (list, tuple, set)):
            return [str(v).strip() for v in value if str(v).strip()]
        return [str(value).strip()] if str(value).strip() else []

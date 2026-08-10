"""Unified message format for all IM platforms.

All platform adapters normalise their native payloads into IMessage,
and the Agent responds with plain text that the adapter renders back.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class IMessage:
    """Normalised inbound message from any IM platform."""

    platform: str  # "telegram" | "feishu" | "dingtalk" | "wecom" | ...
    chat_id: str  # group id or user id (platform-specific)
    chat_type: str  # "dm" | "group" | "channel"
    user_id: str  # sender id
    user_name: str  # sender display name
    content: str  # plain text (media extracted to media_urls)
    message_id: str  # platform-unique id for dedup

    timestamp: datetime = field(default_factory=datetime.now)

    # Thread / topic support
    thread_id: str | None = None  # forum topic, feishu thread, etc.

    # Reply context
    reply_to: str | None = None  # id of message being replied to
    reply_to_text: str | None = None  # text of replied-to message

    # Media attachments — local file paths
    media_urls: list[str] = field(default_factory=list)
    media_types: list[str] = field(default_factory=list)

    # Raw platform payload (debug / advanced use)
    raw_payload: Any = None

    @property
    def session_key(self) -> str:
        """Stable key for session routing: platform + chat_id."""
        return f"{self.platform}:{self.chat_id}"

    @property
    def is_command(self) -> bool:
        return self.content.startswith("/")


@dataclass
class SendResult:
    """Result of sending an outbound message."""
    success: bool
    message_id: str | None = None
    error: str | None = None
    raw_response: Any = None


class MessageDeduplicator:
    """In-memory message dedup with TTL-based eviction."""

    def __init__(self, ttl_seconds: int = 300, max_size: int = 10000):
        import time
        self._ttl = ttl_seconds
        self._max = max_size
        self._seen: dict[str, float] = {}

    def is_duplicate(self, message_id: str) -> bool:
        import time
        if not message_id:
            return False
        now = time.time()
        # Evict expired
        expired = [mid for mid, ts in self._seen.items() if now - ts > self._ttl]
        for mid in expired:
            del self._seen[mid]
        if message_id in self._seen:
            return True
        # Evict oldest if at capacity
        if len(self._seen) >= self._max:
            oldest = min(self._seen, key=self._seen.get)  # type: ignore[arg-type]
            del self._seen[oldest]
        self._seen[message_id] = now
        return False

    def clear(self):
        self._seen.clear()

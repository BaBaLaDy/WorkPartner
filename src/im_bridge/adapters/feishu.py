"""Feishu (Lark) adapter for WorkPartner IM Bridge.

Uses lark-oapi SDK for WebSocket long-connection (recommended) or HTTP webhook.

Env vars:
    FEISHU_APP_ID           App ID from Feishu developer console
    FEISHU_APP_SECRET       App Secret
    FEISHU_VERIFY_TOKEN     Verification token (webhook mode)
    FEISHU_ENCRYPT_KEY      Event encryption key (webhook mode, optional)
    FEISHU_CONNECTION_MODE  "websocket" (default) or "webhook"
    FEISHU_WEBHOOK_HOST     Webhook listen host (default "0.0.0.0")
    FEISHU_WEBHOOK_PORT     Webhook listen port (default 8899)
    FEISHU_WEBHOOK_PATH     Webhook URL path (default "/feishu/webhook")
    FEISHU_BOT_OPEN_ID      Bot open_id override (auto-detected if unset)

config.yaml:
    im_bridge:
      adapters:
        feishu:
          enabled: true
          app_id: "${FEISHU_APP_ID}"
          app_secret: "${FEISHU_APP_SECRET}"
          connection_mode: "websocket"
          dm_policy: "open"          # open | allowlist | disabled
          group_policy: "mention"    # open | mention | disabled
          allow_from: []
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac as _hmac
import json
import logging
import os
import queue
import threading
import time
from typing import TYPE_CHECKING

from ..base import BaseAdapter
from ..message import IMessage, SendResult



if TYPE_CHECKING:
    from ..bridge import BridgeManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SDK availability
# ---------------------------------------------------------------------------

_LARK_AVAILABLE = False
try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
        GetMessageResourceRequest,
        ReplyMessageRequest,
        ReplyMessageRequestBody,
    )
    from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
    from lark_oapi.ws import Client as FeishuWSClient

    _LARK_AVAILABLE = True
except ImportError:
    pass

_AIOHTTP_AVAILABLE = False
try:
    import aiohttp
    from aiohttp import web

    _AIOHTTP_AVAILABLE = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_MESSAGE_LENGTH = 15000
_FEISHU_DOMAIN = "https://open.feishu.cn"
_DEFAULT_WEBHOOK_PATH = "/feishu/webhook"
_DEFAULT_WEBHOOK_HOST = "0.0.0.0"
_DEFAULT_WEBHOOK_PORT = 8899

# Text batching: merge Feishu client-side message splits
_TEXT_BATCH_DELAY = 0.6  # seconds to wait for next chunk
_TEXT_BATCH_SPLIT_DELAY = 2.0  # longer wait when near character limit

# Typing indicator: reaction-based (Feishu has no native typing API)
_FEISHU_REACTION_IN_PROGRESS = "Typing"
_FEISHU_PROCESSING_REACTION_CACHE_SIZE = 1024

# ---------------------------------------------------------------------------
# WebSocket runner (runs in dedicated thread)
# ---------------------------------------------------------------------------


def _run_ws_client(ws_client: FeishuWSClient, adapter: "FeishuAdapter") -> None:
    """Run the Feishu WebSocket client in its own event loop on a daemon thread."""
    import lark_oapi.ws.client as ws_client_module

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    ws_client_module.loop = loop
    adapter._ws_thread_loop = loop

    try:
        loop.run_until_complete(ws_client.start())
    except RuntimeError as e:
        # Expected when disconnect() calls loop.stop() mid-run
        if "Event loop stopped before Future completed" in str(e):
            logger.info("[feishu] WebSocket client stopped (shutdown)")
        else:
            logger.exception("[feishu] WebSocket client exited with error")
    except Exception:
        logger.exception("[feishu] WebSocket client exited with error")
    finally:
        adapter._ws_thread_loop = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_text_payload(text: str) -> str:
    return json.dumps({"text": text}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class FeishuAdapter(BaseAdapter):
    """Feishu (Lark) bot adapter.

    Connects via WebSocket long-connection (default) or HTTP webhook.
    WebSocket runs in a dedicated daemon thread since lark-oapi uses a
    synchronous start() method.
    """

    platform = "feishu"
    MAX_MESSAGE_LENGTH = MAX_MESSAGE_LENGTH

    def __init__(self, config: dict, bridge: "BridgeManager"):
        super().__init__(config, bridge)
        self._app_id = os.getenv("FEISHU_APP_ID", config.get("app_id", "")).strip()
        self._app_secret = os.getenv("FEISHU_APP_SECRET", config.get("app_secret", "")).strip()
        self._verify_token = os.getenv("FEISHU_VERIFY_TOKEN", config.get("verify_token", "")).strip()
        self._encrypt_key = os.getenv("FEISHU_ENCRYPT_KEY", config.get("encrypt_key", "")).strip()
        self._connection_mode = os.getenv(
            "FEISHU_CONNECTION_MODE", config.get("connection_mode", "websocket"),
        ).strip()

        # Policies
        self._dm_policy = config.get("dm_policy", "open")
        self._group_policy = config.get("group_policy", "mention")
        self._allow_from = self._coerce_list(config.get("allow_from", []))

        # Webhook settings
        self._webhook_host = os.getenv(
            "FEISHU_WEBHOOK_HOST", config.get("webhook_host", _DEFAULT_WEBHOOK_HOST),
        ).strip()
        self._webhook_port = int(os.getenv(
            "FEISHU_WEBHOOK_PORT", config.get("webhook_port", str(_DEFAULT_WEBHOOK_PORT)),
        ))
        self._webhook_path = os.getenv(
            "FEISHU_WEBHOOK_PATH", config.get("webhook_path", _DEFAULT_WEBHOOK_PATH),
        ).strip()

        # State
        self._client: lark.Client | None = None
        self._ws_client: FeishuWSClient | None = None
        self._ws_thread_loop: asyncio.AbstractEventLoop | None = None
        self._event_handler: EventDispatcherHandler | None = None
        self._web_runner: web.AppRunner | None = None
        self._web_site: web.TCPSite | None = None
        self._bot_open_id: str = os.getenv("FEISHU_BOT_OPEN_ID", "").strip()
        self._bot_name: str = ""
        self._connecting: bool = False  # guard against concurrent connect() calls

        # Event queue for reliable cross-thread message passing (thread-safe)
        self._event_queue: queue.Queue | None = None
        self._event_consumer: asyncio.Task | None = None
        self._connect_time: float = 0  # timestamp when connection was established

        # Text batching state — uses generation counter instead of task cancellation
        # to avoid cancelling the agent mid-run when new chunks arrive.
        self._text_batch: dict[str, IMessage] = {}
        self._text_batch_tasks: dict[str, asyncio.Task] = {}
        self._text_batch_gen: dict[str, int] = {}

        # Typing indicator: reaction_id cache (LRU) mapping message_id → reaction_id
        self._pending_processing_reactions: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        # Guard against concurrent/repeated connect() calls while already connecting or connected
        if self._connecting:
            logger.warning("[feishu] connect() already in progress, ignoring duplicate call")
            return False
        if self._ws_client is not None or self._web_runner is not None:
            logger.warning("[feishu] Already connected, ignoring duplicate call")
            return True
        if not _LARK_AVAILABLE:
            logger.error("[feishu] lark-oapi not installed. Run: pip install lark-oapi")
            return False
        if not self._app_id or not self._app_secret:
            logger.error("[feishu] FEISHU_APP_ID and FEISHU_APP_SECRET are required")
            return False

        self._connecting = True
        try:
            # Build API client
            self._client = (
                lark.Client.builder()
                .app_id(self._app_id)
                .app_secret(self._app_secret)
                .domain(_FEISHU_DOMAIN)
                .log_level(lark.LogLevel.WARNING)
                .build()
            )

            # Create thread-safe event queue and start consumer on main loop
            self._event_queue = queue.Queue()
            self._event_consumer = asyncio.create_task(self._event_consumer_loop())
            self._connect_time = time.time()  # Ignore events from before this timestamp
            self._running = True  # Set BEFORE any awaits so consumer loop sees it as True

            # Build event handler (callbacks are sync — SDK calls them in its own thread)
            self._event_handler = (
                EventDispatcherHandler.builder(
                    self._encrypt_key, self._verify_token,
                )
                .register_p2_im_message_receive_v1(self._on_message_event)
                .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(
                    lambda data: logger.info("[feishu] User entered bot chat")
                )
                .register_p2_im_chat_member_bot_added_v1(self._on_bot_added)
                .register_p2_im_chat_member_bot_deleted_v1(
                    lambda data: logger.info("[feishu] Bot removed from group chat")
                )
                # Suppress "processor not found" for these common events
                .register_p2_im_message_message_read_v1(
                    lambda data: None
                )
                .register_p2_im_message_reaction_created_v1(
                    lambda data: None
                )
                .register_p2_im_message_reaction_deleted_v1(
                    lambda data: None
                )
                .register_p2_im_message_recalled_v1(
                    lambda data: None
                )
                .register_p2_card_action_trigger(
                    lambda data: logger.info("[feishu] Card action triggered")
                )
                .build()
            )

            # Hydrate bot identity for mention detection
            await self._hydrate_bot_identity()

            # Connect based on mode
            if self._connection_mode == "webhook":
                if not _AIOHTTP_AVAILABLE:
                    logger.error("[feishu] aiohttp required for webhook mode")
                    return False
                await self._start_webhook()
            else:
                self._start_websocket()

            logger.info("[feishu] Connected (%s mode), bot open_id=%s",
                         self._connection_mode, self._bot_open_id[:20] if self._bot_open_id else "?")
            return True

        except Exception as e:
            logger.error("[feishu] Connection failed: %s", e, exc_info=True)
            return False
        finally:
            self._connecting = False

    async def disconnect(self) -> None:
        self._running = False
        self._connecting = False  # Unblock any pending connect()

        # Stop event consumer
        if self._event_consumer and not self._event_consumer.done():
            try:
                await asyncio.wait_for(self._event_consumer, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._event_consumer.cancel()
        # Drain remaining events from queue before cleanup
        while self._event_queue and not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except queue.Empty:
                break
        self._event_consumer = None
        self._event_queue = None

        # Cancel pending text batch tasks
        for task in self._text_batch_tasks.values():
            if not task.done():
                task.cancel()
        self._text_batch_tasks.clear()
        self._text_batch.clear()

        # Stop WebSocket
        if self._ws_thread_loop and not self._ws_thread_loop.is_closed():
            try:
                self._ws_thread_loop.stop()
            except Exception:
                pass
        self._ws_thread_loop = None
        self._ws_client = None

        # Stop webhook
        if self._web_runner:
            try:
                await self._web_runner.cleanup()
            except Exception:
                pass
        self._web_runner = None
        self._web_site = None

        self._client = None
        self._event_handler = None
        logger.info("[feishu] Disconnected")

    # ------------------------------------------------------------------
    # Bot group membership events
    # ------------------------------------------------------------------

    def _on_bot_added(self, data) -> None:
        """Bot was added to a group chat — log the chat_id prominently."""
        try:
            event = getattr(data, "event", None) or {}
            if hasattr(event, "__dict__"):
                event = vars(event)
            chat_id = ""
            if isinstance(event, dict):
                chat_id = (
                    event.get("chat_id")
                    or (event.get("chat") or {}).get("chat_id", "")
                )
            print(
                f"\n{'=' * 60}\n"
                f"[feishu] Bot added to group chat!\n"
                f"  chat_id = {chat_id}\n"
                f"Add this to config.yaml under im.targets to enable group notifications.\n"
                f"{'=' * 60}\n",
                flush=True,
            )
            logger.info("[feishu] Bot added to group chat, chat_id=%s", chat_id)
        except Exception:
            logger.exception("[feishu] Error in _on_bot_added")

    # ------------------------------------------------------------------
    # Bot identity
    # ------------------------------------------------------------------

    async def _hydrate_bot_identity(self) -> None:
        """Discover bot open_id for mention detection in group chats."""
        if self._bot_open_id and self._bot_name:
            return
        if not self._client:
            return

        try:
            from lark_oapi.core import AccessTokenType, HttpMethod
            from lark_oapi.core.model.base_request import BaseRequest

            req = (
                BaseRequest.builder()
                .http_method(HttpMethod.GET)
                .uri("/open-apis/bot/v3/info")
                .token_types({AccessTokenType.TENANT})
                .build()
            )
            resp = await asyncio.to_thread(self._client.request, req)
            raw = getattr(resp, "raw", None)
            if raw and hasattr(raw, "content"):
                data = json.loads(raw.content)
                bot_info = data.get("data", {}).get("bot", {}) if isinstance(data, dict) else {}
                if not self._bot_open_id:
                    self._bot_open_id = bot_info.get("open_id", "")
                if not self._bot_name:
                    self._bot_name = bot_info.get("app_name", "")

        except Exception as e:
            logger.warning("[feishu] Could not get bot identity: %s", e)

    # ------------------------------------------------------------------
    # WebSocket mode
    # ------------------------------------------------------------------

    def _start_websocket(self) -> None:
        """Start Feishu WebSocket long-connection in a daemon thread."""
        ws_client = FeishuWSClient(
            app_id=self._app_id,
            app_secret=self._app_secret,
            log_level=lark.LogLevel.INFO,
            event_handler=self._event_handler,
            domain=_FEISHU_DOMAIN,
            auto_reconnect=True,
        )
        self._ws_client = ws_client

        import threading
        thread = threading.Thread(
            target=_run_ws_client,
            args=(ws_client, self),
            daemon=True,
        )
        thread.start()

    # ------------------------------------------------------------------
    # Webhook mode
    # ------------------------------------------------------------------

    async def _start_webhook(self) -> None:
        """Start aiohttp webhook server."""
        app = web.Application()
        app.router.add_post(self._webhook_path, self._handle_webhook)
        app.router.add_get(self._webhook_path, self._handle_webhook_verify)

        self._web_runner = web.AppRunner(app)
        await self._web_runner.setup()
        self._web_site = web.TCPSite(self._web_runner, self._webhook_host, self._webhook_port)
        await self._web_site.start()
        logger.info("[feishu] Webhook listening on %s:%d%s",
                     self._webhook_host, self._webhook_port, self._webhook_path)

    async def _handle_webhook_verify(self, request: web.Request) -> web.Response:
        """Handle Feishu URL verification challenge."""
        challenge = request.query.get("challenge", "")
        if challenge:
            return web.json_response({"challenge": challenge})
        return web.Response(text="ok")

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        """Handle inbound webhook events."""
        try:
            body = await request.json()
        except Exception:
            return web.Response(text="invalid json", status=400)

        # URL verification
        if body.get("type") == "url_verification":
            return web.json_response({"challenge": body.get("challenge", "")})

        # Verify the event token when a verification token is configured —
        # without this check anyone who discovers the endpoint could forge
        # events and drive the agent.
        header = body.get("header", {})
        if self._verify_token and header.get("token") != self._verify_token:
            logger.warning("[feishu] Webhook event rejected: token mismatch")
            return web.Response(text="invalid token", status=403)

        # Process event
        event_type = header.get("event_type", "")
        event_data = body.get("event", {})

        if event_type == "im.message.receive_v1":
            asyncio.create_task(self._handle_inbound_message(event_data))

        return web.Response(text="ok")

    # ------------------------------------------------------------------
    # Event handler (WebSocket)
    # ------------------------------------------------------------------

    @staticmethod
    def _obj_to_dict(obj) -> dict:
        """Recursively convert SDK objects (EventMessage, etc.) to plain dicts."""
        if isinstance(obj, dict):
            return {k: FeishuAdapter._obj_to_dict(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [FeishuAdapter._obj_to_dict(v) for v in obj]
        if hasattr(obj, "__dict__") and not isinstance(obj, (str, bytes)):
            result = {}
            for k, v in vars(obj).items():
                if not k.startswith("_"):
                    result[k] = FeishuAdapter._obj_to_dict(v)
            return result
        return obj

    def _on_message_event(self, data) -> None:
        """Handle im.message.receive_v1 event from WebSocket (called in WS thread)."""
        try:
            event = getattr(data, "event", None)
            if event is None:
                logger.debug("[feishu] _on_message_event: no event attribute")
                return
            if isinstance(event, dict):
                event_dict = FeishuAdapter._obj_to_dict(event)
            elif hasattr(event, "__dict__") and not isinstance(event, (str, bytes)):
                event_dict = FeishuAdapter._obj_to_dict(vars(event))
            else:
                logger.debug("[feishu] _on_message_event: unsupported event type: %s", type(event).__name__)
                return
            # Put event into thread-safe queue — consumer task on main loop will pick it up
            if self._event_queue is not None:
                self._event_queue.put_nowait(event_dict)
            else:
                logger.warning("[feishu] Event queue not ready, dropping event")
        except Exception:
            logger.exception("[feishu] Error processing WS message event")

    async def _event_consumer_loop(self) -> None:
        """Consumer loop: pull events from thread-safe queue and process on main loop."""
        while self._running:
            try:
                # Non-blocking get with short timeout to allow loop to check self._running
                event = self._event_queue.get_nowait()
                logger.debug("[feishu] Consumer picked up event from queue")
                await self._handle_inbound_message(event)
            except queue.Empty:
                await asyncio.sleep(0.1)
            except Exception:
                logger.exception("[feishu] Consumer error processing event")

    # ------------------------------------------------------------------
    # Inbound message processing
    # ------------------------------------------------------------------

    async def _handle_inbound_message(self, event: dict) -> None:
        """Process an inbound message event (from WS or webhook)."""
        try:
            message = event.get("message", {})
            if not message:
                logger.debug("[feishu] _handle_inbound_message: no message in event, event=%s", json.dumps(event, ensure_ascii=False)[:500])
                return

            # Sender info — resolve first so we can use it for user_name
            sender = event.get("sender", {})
            sender_id = sender.get("sender_id", {})
            if isinstance(sender_id, dict):
                user_id = str(sender_id.get("open_id") or sender_id.get("user_id") or "")
            else:
                user_id = str(sender_id) if sender_id else ""

            message_id = str(message.get("message_id", ""))
            chat_id = str(message.get("chat_id", ""))
            # SDK field is "message_type", not "msg_type"
            msg_type = str(message.get("message_type", "text"))

            if not chat_id or not user_id:
                logger.debug("[feishu] Skipping: chat_id=%s, user_id=%s", chat_id, user_id)
                return

            # Skip stale messages from before this connection was established
            msg_create_time = int(message.get("create_time", 0) or 0)  # milliseconds
            if msg_create_time and msg_create_time < self._connect_time * 1000:
                logger.debug("[feishu] Skipping stale message %s (created=%d, connected=%d)",
                             message_id, msg_create_time, self._connect_time * 1000)
                return

            # Chat type — use the SDK field "chat_type" ("p2p"/"group"), not chat_id prefix
            raw_chat_type = message.get("chat_type", "")
            chat_type = "group" if raw_chat_type == "group" else "dm"

            # Extract text content
            content = self._extract_text(message, msg_type)
            if not content and msg_type == "text":
                return
            if not content:
                content = "[non-text message]"

            # Policy checks
            if not self._check_policy(chat_type, user_id, message):
                logger.info("[feishu] Message dropped by policy: chat_type=%s, user_id=%s", chat_type, user_id[:10])
                return

            user_name = sender.get("sender_name", user_id[:10])

            # Build IMessage
            msg = IMessage(
                platform="feishu",
                chat_id=chat_id,
                chat_type=chat_type,
                user_id=user_id,
                user_name=user_name,
                content=content,
                message_id=message_id,
                thread_id=message.get("thread_id"),
                reply_to=message.get("root_id"),
                raw_payload=event,
            )

            logger.info("[feishu] Processing: user=%s, content=%r", user_name, content[:80])

            # Download media
            await self._download_media(message, msg)

            # Route through text batching (merges client-side splits)
            if msg_type == "text":
                self._enqueue_text(msg)
            else:
                await self.handle_message(msg)

        except Exception:
            logger.exception("[feishu] Error processing inbound message")

    def _check_policy(self, chat_type: str, user_id: str, message: dict) -> bool:
        """Apply DM/group policy checks."""
        if chat_type == "group":
            if self._group_policy == "disabled":
                return False
            if self._group_policy == "allowlist" and user_id not in self._allow_from:
                return False
            if self._group_policy == "mention":
                mentions = message.get("mentions", [])
                if mentions:
                    # If we know bot open_id, check exact match
                    if self._bot_open_id:
                        has_bot = any(
                            (m.get("id", {}) if isinstance(m, dict) else {}).get("open_id", "") == self._bot_open_id
                            for m in mentions
                        )
                        if not has_bot:
                            return False
                    # If we don't know bot open_id, trust mentions array
                else:
                    # No mentions — check content for @ pattern as fallback
                    content = self._extract_text(message, message.get("msg_type", "text"))
                    if "@" not in content:
                        return False
        else:
            if self._dm_policy == "disabled":
                return False
            if self._dm_policy == "allowlist" and user_id not in self._allow_from:
                return False

        return True

    def _extract_text(self, message: dict, msg_type: str) -> str:
        """Extract plain text from a Feishu message."""
        if msg_type == "text":
            content_block = message.get("content", "{}")
            if isinstance(content_block, str):
                try:
                    content_block = json.loads(content_block)
                except json.JSONDecodeError:
                    return content_block
            return content_block.get("text", "") if isinstance(content_block, dict) else str(content_block)

        if msg_type == "post":
            content_block = message.get("content", "{}")
            if isinstance(content_block, str):
                try:
                    content_block = json.loads(content_block)
                except json.JSONDecodeError:
                    return "[rich post]"
            parts = []
            if isinstance(content_block, dict):
                for para in content_block.get("content", [[]]):
                    if isinstance(para, list):
                        for segment in para:
                            if isinstance(segment, dict):
                                parts.append(segment.get("text", ""))
            return "\n".join(parts) if parts else "[rich post]"

        if msg_type in ("image", "media"):
            image_key = message.get("image_key", "")
            return f"[image: {image_key}]"

        if msg_type == "file":
            file_name = message.get("file_name", "unknown")
            return f"[file: {file_name}]"

        if msg_type == "audio":
            return "[voice message]"

        if msg_type == "sticker":
            return "[sticker]"

        return f"[{msg_type} message]"

    async def _download_media(self, message: dict, msg: IMessage) -> None:
        """Download Feishu media attachments."""
        msg_type = message.get("msg_type", "")
        if msg_type not in ("image", "file", "media"):
            return

        try:
            cache_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
                "history", "media_cache",
            )
            os.makedirs(cache_dir, exist_ok=True)

            message_id = message.get("message_id", "")
            file_key = message.get("file_key", "") or message.get("image_key", "")
            if not message_id or not file_key or not self._client:
                return

            from lark_oapi.api.im.v1 import GetMessageResourceRequest

            resp = self._client.im.v1.get_message_resource(
                GetMessageResourceRequest(message_id=message_id, file_key=file_key, type=msg_type)
            )

            if resp.success() and resp.file:
                ext_map = {"image": ".jpg", "file": ".bin", "media": ".bin"}
                ext = ext_map.get(msg_type, ".bin")
                path = os.path.join(cache_dir, f"feishu_{message_id}{ext}")

                with open(path, "wb") as f:
                    f.write(resp.file.read())

                msg.media_urls.append(path)
                mime_map = {"image": "image/jpeg", "file": "application/octet-stream"}
                msg.media_types.append(mime_map.get(msg_type, "application/octet-stream"))

        except Exception as e:
            logger.warning("[feishu] Media download failed: %s", e)

    # ------------------------------------------------------------------
    # Text batching (merge Feishu client-side message splits)
    # ------------------------------------------------------------------

    def _text_batch_key(self, msg: IMessage) -> str:
        return msg.session_key

    def _enqueue_text(self, msg: IMessage) -> None:
        """Debounce rapid text bursts from Feishu into a single message."""
        key = self._text_batch_key(msg)
        chunk_len = len(msg.content)
        existing = self._text_batch.get(key)

        if existing is None:
            msg._last_chunk_len = chunk_len  # type: ignore[attr-defined]
            self._text_batch[key] = msg
        else:
            existing.content = f"{existing.content}\n{msg.content}"
            existing._last_chunk_len = chunk_len  # type: ignore[attr-defined]

        # Reset the timer — cancel old task (but handle_message is shielded)
        prior = self._text_batch_tasks.get(key)
        if prior and not prior.done():
            prior.cancel()
        self._text_batch_tasks[key] = asyncio.create_task(self._flush_text(key))

    async def _flush_text(self, key: str) -> None:
        """Flush a text batch after the debounce delay."""
        try:
            pending = self._text_batch.get(key)
            last_len = getattr(pending, "_last_chunk_len", 0) if pending else 0
            delay = _TEXT_BATCH_SPLIT_DELAY if last_len >= MAX_MESSAGE_LENGTH * 0.9 else _TEXT_BATCH_DELAY
            await asyncio.sleep(delay)
            msg = self._text_batch.pop(key, None)
            if msg is None:
                return
            # Shield the agent call so debounce cancellations don't kill the in-flight run
            await asyncio.shield(self.handle_message(msg))
        except asyncio.CancelledError:
            # Expected when debouncing: newer chunk cancelled this flush
            pass
        except Exception:
            logger.exception("[feishu] Text flush error")
        finally:
            self._text_batch_tasks.pop(key, None)

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def send(
        self,
        chat_id: str,
        content: str,
        *,
        reply_to: str | None = None,
        thread_id: str | None = None,
    ) -> SendResult:
        if not self._client:
            return SendResult(success=False, error="Not connected")
        if not content or not content.strip():
            return SendResult(success=True, message_id=None)

        try:
            chunks = self.split_text(content, self.MAX_MESSAGE_LENGTH)
            last_message_id = None

            # Determine receive_id_type: oc_ = group chat_id, ou_ = user open_id
            if chat_id.startswith("oc_"):
                receive_id_type = "chat_id"
            elif chat_id.startswith("ou_"):
                receive_id_type = "open_id"
            else:
                # Fallback: try chat_id
                receive_id_type = "chat_id"

            for chunk in chunks:
                payload = _build_text_payload(chunk)

                if reply_to:
                    body = (
                        ReplyMessageRequestBody.builder()
                        .content(payload)
                        .msg_type("text")
                        .build()
                    )
                    req = (
                        ReplyMessageRequest.builder()
                        .message_id(reply_to)
                        .request_body(body)
                        .build()
                    )
                    resp = await asyncio.to_thread(self._client.im.v1.message.reply, req)
                else:
                    body = (
                        CreateMessageRequestBody.builder()
                        .receive_id(chat_id)
                        .msg_type("text")
                        .content(payload)
                        .build()
                    )
                    req = (
                        CreateMessageRequest.builder()
                        .receive_id_type(receive_id_type)
                        .request_body(body)
                        .build()
                    )
                    resp = await asyncio.to_thread(self._client.im.v1.message.create, req)

                if resp and resp.success():
                    last_message_id = resp.data.message_id if resp.data else None
                else:
                    logger.warning("[feishu] Send chunk failed: %s",
                                   resp.data if resp and resp.data else "no response")

            if last_message_id:
                return SendResult(success=True, message_id=last_message_id)
            return SendResult(success=False, error="API returned no message ID")

        except Exception as e:
            logger.error("[feishu] Send failed to %s: %s", chat_id, e)
            return SendResult(success=False, error=str(e))

    # ------------------------------------------------------------------
    # Typing indicator — reaction-based (Feishu has no native typing API)
    # ------------------------------------------------------------------

    async def _add_reaction(self, message_id: str, emoji_type: str) -> str | None:
        """Add a reaction badge to a message. Returns the reaction_id on success."""
        if not self._client:
            return None
        try:
            from lark_oapi.api.im.v1 import (
                CreateMessageReactionRequest,
                CreateMessageReactionRequestBody,
            )
            body = (
                CreateMessageReactionRequestBody.builder()
                .reaction_type({"emoji_type": emoji_type})
                .build()
            )
            req = (
                CreateMessageReactionRequest.builder()
                .message_id(message_id)
                .request_body(body)
                .build()
            )
            resp = await asyncio.to_thread(self._client.im.v1.message_reaction.create, req)
            if resp and getattr(resp, "success", lambda: False)():
                data = getattr(resp, "data", None)
                reaction_id = getattr(data, "reaction_id", None)
                if reaction_id:
                    return reaction_id
            logger.warning("[feishu] Failed to add reaction to %s: code=%s msg=%s",
                           message_id,
                           getattr(resp, "code", None),
                           getattr(resp, "msg", None))
            return None
        except Exception:
            logger.exception("[feishu] Error adding reaction to %s", message_id)
            return None

    async def _remove_reaction(self, message_id: str, reaction_id: str) -> bool:
        """Remove a reaction badge from a message."""
        if not self._client:
            return False
        try:
            from lark_oapi.api.im.v1 import DeleteMessageReactionRequest
            req = (
                DeleteMessageReactionRequest.builder()
                .message_id(message_id)
                .reaction_id(reaction_id)
                .build()
            )
            resp = await asyncio.to_thread(self._client.im.v1.message_reaction.delete, req)
            if resp and getattr(resp, "success", lambda: False)():
                return True
            logger.warning("[feishu] Failed to remove reaction %s from %s: code=%s msg=%s",
                           reaction_id, message_id,
                           getattr(resp, "code", None),
                           getattr(resp, "msg", None))
            return False
        except Exception:
            logger.exception("[feishu] Error removing reaction %s from %s", reaction_id, message_id)
            return False

    def _remember_processing_reaction(self, message_id: str, reaction_id: str) -> None:
        """Store reaction_id in LRU cache for later removal."""
        cache = self._pending_processing_reactions
        cache[message_id] = reaction_id
        if len(cache) > _FEISHU_PROCESSING_REACTION_CACHE_SIZE:
            cache.pop(next(iter(cache)))

    def _pop_processing_reaction(self, message_id: str) -> str | None:
        return self._pending_processing_reactions.pop(message_id, None)

    async def _process_message(self, msg: IMessage) -> str | None:
        """Override: add Typing reaction before agent runs, remove after;
        and ensure agent replies thread to the user's original message."""
        # Show typing indicator on user's original message
        if msg.message_id and msg.message_id not in self._pending_processing_reactions:
            reaction_id = await self._add_reaction(msg.message_id, _FEISHU_REACTION_IN_PROGRESS)
            if reaction_id:
                self._remember_processing_reaction(msg.message_id, reaction_id)

        # If user didn't reply to a specific message, thread agent reply to theirs
        if not msg.reply_to:
            msg.reply_to = msg.message_id

        try:
            return await super()._process_message(msg)
        finally:
            # Remove typing indicator (the reply itself is the success signal;
            # on failure the error message also serves as signal)
            if msg.message_id:
                reaction_id = self._pop_processing_reaction(msg.message_id)
                if reaction_id:
                    await self._remove_reaction(msg.message_id, reaction_id)

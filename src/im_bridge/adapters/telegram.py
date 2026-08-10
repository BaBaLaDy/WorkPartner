"""Telegram adapter for WorkPartner IM Bridge.

Uses python-telegram-bot for async long-polling (default) or webhook.

Env vars:
    TELEGRAM_BOT_TOKEN       Bot token from @BotFather (required)
    TELEGRAM_WEBHOOK_URL     Public HTTPS URL for webhook mode (optional)
    TELEGRAM_WEBHOOK_PORT    Webhook listen port (default 8443)
    TELEGRAM_ALLOWED_USERS   Comma-separated list of allowed user IDs

config.yaml:
    im_bridge:
      adapters:
        telegram:
          enabled: true
          token: "${TELEGRAM_BOT_TOKEN}"
          dm_policy: "open"        # open | allowlist | disabled
          group_policy: "open"     # open | allowlist | disabled
          allow_from: []           # user ID allowlist
          connection_mode: "polling"  # polling | webhook
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import TYPE_CHECKING

from ..base import BaseAdapter
from ..message import IMessage, SendResult

if TYPE_CHECKING:
    from ..bridge import BridgeManager

logger = logging.getLogger(__name__)

TELEGRAM_AVAILABLE = False
try:
    from telegram import Update, BotCommand
    from telegram.error import NetworkError, TimedOut, BadRequest
    from telegram.ext import (
        Application,
        ApplicationBuilder,
        MessageHandler as TelegramMessageHandler,
        CommandHandler,
        CallbackQueryHandler,
        filters,
        ContextTypes,
    )
    from telegram.constants import ParseMode

    TELEGRAM_AVAILABLE = True
except ImportError:
    pass

MAX_MESSAGE_LENGTH = 4096


# ---------------------------------------------------------------------------
# MarkdownV2 helper
# ---------------------------------------------------------------------------

_MDV2_ESCAPE_RE = re.compile(r'([_*\[\]()~`>#+\-=|{}.!\\])')


def _escape_mdv2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return _MDV2_ESCAPE_RE.sub(r'\\\1', text)


def _to_markdown_v2(text: str) -> str:
    """Convert common Markdown to Telegram MarkdownV2.

    Preserves code blocks, converts **bold** and *italic*, escapes the rest.
    """
    if not text:
        return text

    pl: dict[str, str] = {}
    counter = [0]

    def _ph(value: str) -> str:
        key = f"\x00PH{counter[0]}\x00"
        counter[0] += 1
        pl[key] = value
        return key

    # 1. Protect fenced code blocks
    text = re.sub(
        r'(```(?:[^\n]*\n)?.*?```)',
        lambda m: _ph(m.group(0)),
        text,
        flags=re.DOTALL,
    )

    # 2. Protect inline code
    text = re.sub(r'(`[^`]+`)', lambda m: _ph(m.group(0)), text)

    # 3. Convert **bold** → *bold* (protect from escaping)
    text = re.sub(r'\*\*(.+?)\*\*', lambda m: _ph(f"*{m.group(1)}*"), text)

    # 4. Convert __underline__ → _italic_ (protect from escaping)
    text = re.sub(r'__(.+?)__', lambda m: _ph(f"_{m.group(1)}_"), text)

    # 5. Escape remaining special chars
    text = _MDV2_ESCAPE_RE.sub(r'\\\1', text)

    # Restore protected regions (newest first)
    for ph_key in reversed(pl):
        text = text.replace(ph_key, pl[ph_key])

    return text


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class TelegramAdapter(BaseAdapter):
    """Telegram bot adapter.

    Connects via long-polling (default) or webhook.
    """

    platform = "telegram"
    MAX_MESSAGE_LENGTH = MAX_MESSAGE_LENGTH
    _SPLIT_THRESHOLD = 3900  # near limit → longer batch wait

    def __init__(self, config: dict, bridge: "BridgeManager"):
        super().__init__(config, bridge)
        self._token = os.getenv("TELEGRAM_BOT_TOKEN", config.get("token", "")).strip()
        self._app: Application | None = None
        self._dm_policy = config.get("dm_policy", "open")
        self._group_policy = config.get("group_policy", "open")
        self._allow_from = self._coerce_list(config.get("allow_from", []))
        self._connection_mode = config.get("connection_mode", "polling")
        # Text batching for client-side message splits
        self._text_batch_delay = float(os.getenv("HERMES_TELEGRAM_TEXT_BATCH_DELAY", "0.6"))
        self._text_batch_split_delay = float(os.getenv("HERMES_TELEGRAM_TEXT_BATCH_SPLIT_DELAY", "2.0"))
        self._pending_text: dict[str, IMessage] = {}
        self._pending_text_tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        if not TELEGRAM_AVAILABLE:
            logger.error("[telegram] python-telegram-bot not installed. Run: pip install python-telegram-bot")
            return False
        if not self._token:
            logger.error("[telegram] No bot token configured (set TELEGRAM_BOT_TOKEN)")
            return False

        try:
            builder = ApplicationBuilder().token(self._token)

            # Optional proxy
            proxy_url = os.getenv("TELEGRAM_PROXY", "")
            if proxy_url:
                builder = builder.proxy_url(proxy_url)

            self._app = builder.build()

            # Register handlers
            self._app.add_handler(TelegramMessageHandler(
                filters.TEXT & ~filters.COMMAND, self._handle_text,
            ))
            self._app.add_handler(TelegramMessageHandler(
                filters.COMMAND, self._handle_command,
            ))
            self._app.add_handler(TelegramMessageHandler(
                filters.PHOTO | filters.VIDEO | filters.AUDIO |
                filters.VOICE | filters.Document.ALL,
                self._handle_media,
            ))
            self._app.add_handler(CallbackQueryHandler(self._handle_callback))

            # Start
            await self._app.initialize()
            await self._app.start()

            if self._connection_mode == "webhook":
                webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL", "")
                webhook_port = int(os.getenv("TELEGRAM_WEBHOOK_PORT", "8443"))
                webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
                if webhook_url:
                    from urllib.parse import urlparse
                    webhook_path = urlparse(webhook_url).path or "/telegram"
                    await self._app.updater.start_webhook(
                        listen="0.0.0.0", port=webhook_port,
                        url_path=webhook_path, webhook_url=webhook_url,
                        secret_token=webhook_secret or None,
                        allowed_updates=Update.ALL_TYPES,
                        drop_pending_updates=True,
                    )
                    logger.info("[telegram] Webhook mode on 0.0.0.0:%d%s", webhook_port, webhook_path)
            else:
                await self._app.updater.start_polling(
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True,
                )
                logger.info("[telegram] Polling mode started")

            # Register bot commands for the menu
            try:
                commands = [
                    BotCommand("new", "开始新会话"),
                    BotCommand("reset", "重置当前会话"),
                    BotCommand("status", "查看状态"),
                ]
                await self._app.bot.set_my_commands(commands)
            except Exception:
                pass

            self._running = True
            logger.info("[telegram] Connected — @%s", (await self._app.bot.get_me()).username)
            return True

        except Exception as e:
            logger.error("[telegram] Connection failed: %s", e)
            return False

    async def disconnect(self) -> None:
        self._running = False
        # Cancel pending text batch tasks
        for task in self._pending_text_tasks.values():
            if not task.done():
                task.cancel()
        self._pending_text_tasks.clear()
        self._pending_text.clear()

        if self._app:
            try:
                if self._app.updater and self._app.updater.running:
                    await self._app.updater.stop()
                if self._app.running:
                    await self._app.stop()
                await self._app.shutdown()
            except Exception as e:
                logger.warning("[telegram] Disconnect error: %s", e)
        self._app = None

    # ------------------------------------------------------------------
    # Inbound handlers
    # ------------------------------------------------------------------

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.text:
            return
        if not self._should_process(update.message):
            return

        msg = self._build_imessage(update)
        self._enqueue_text(msg)

    async def _handle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.text:
            return
        if not self._should_process(update.message, is_command=True):
            return

        msg = self._build_imessage(update)
        cmd = update.message.text.split(maxsplit=1)[0].lower()
        if "@" in cmd:
            cmd = cmd.split("@", 1)[0]

        # Built-in commands
        if cmd in ("/new", "/reset"):
            thread_id = self.bridge.get_or_create_thread(msg.session_key, msg.user_name)
            # Create a fresh session
            self.bridge.agent_session.sessions.create_session(f"{msg.session_key} ({msg.user_name})")
            await self.send(msg.chat_id, "会话已重置。有什么可以帮你的？")
            return

        # Regular command → process as normal message
        await self.handle_message(msg)

    async def _handle_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        if not self._should_process(update.message):
            return

        msg = self._build_imessage(update)
        # Download media to local cache
        await self._download_media(update.message, msg)

        if not msg.content:
            msg.content = "[media message]"
        if msg.media_urls:
            msg.content += "\n[The user sent media — see attached files]"

        await self.handle_message(msg)

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.callback_query:
            return
        query = update.callback_query
        await query.answer()
        # Treat callback data as text input
        data = query.data or ""
        from_user = query.from_user
        if not from_user:
            return

        msg = IMessage(
            platform="telegram",
            chat_id=str(query.message.chat_id if query.message else from_user.id),
            chat_type="dm",
            user_id=str(from_user.id),
            user_name=from_user.full_name or from_user.username or str(from_user.id),
            content=data,
            message_id=f"cb:{query.id}",
        )
        await self.handle_message(msg)

    # ------------------------------------------------------------------
    # Text batching (merge Telegram client-side splits)
    # ------------------------------------------------------------------

    def _text_batch_key(self, msg: IMessage) -> str:
        return msg.session_key

    def _enqueue_text(self, msg: IMessage) -> None:
        key = self._text_batch_key(msg)
        chunk_len = len(msg.content)
        existing = self._pending_text.get(key)
        if existing is None:
            msg._last_chunk_len = chunk_len  # type: ignore[attr-defined]
            self._pending_text[key] = msg
        else:
            existing.content = f"{existing.content}\n{msg.content}"
            existing._last_chunk_len = chunk_len  # type: ignore[attr-defined]

        # Cancel previous timer
        prior = self._pending_text_tasks.get(key)
        if prior and not prior.done():
            prior.cancel()
        self._pending_text_tasks[key] = asyncio.create_task(self._flush_text(key))

    async def _flush_text(self, key: str) -> None:
        try:
            pending = self._pending_text.get(key)
            last_len = getattr(pending, "_last_chunk_len", 0) if pending else 0
            delay = self._text_batch_split_delay if last_len >= self._SPLIT_THRESHOLD else self._text_batch_delay
            await asyncio.sleep(delay)
            msg = self._pending_text.pop(key, None)
            if not msg:
                return
            await self.handle_message(msg)
        finally:
            self._pending_text_tasks.pop(key, None)

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
        if not self._app or not self._app.bot:
            return SendResult(success=False, error="Not connected")
        if not content or not content.strip():
            return SendResult(success=True, message_id=None)

        try:
            formatted = _to_markdown_v2(content)
            # Disable web page preview for cleaner look
            kwargs: dict = {"disable_web_page_preview": True}
            if reply_to:
                kwargs["reply_to_message_id"] = int(reply_to)
            if thread_id and thread_id != "1":
                kwargs["message_thread_id"] = int(thread_id)

            sent = None
            for chunk in self.split_text(formatted, self.MAX_MESSAGE_LENGTH):
                # Only reply to the first chunk
                if sent is not None:
                    kwargs.pop("reply_to_message_id", None)
                try:
                    sent = await self._app.bot.send_message(
                        chat_id=int(chat_id),
                        text=chunk,
                        parse_mode=ParseMode.MARKDOWN_V2,
                        **kwargs,
                    )
                except BadRequest as exc:
                    # MarkdownV2 parsing failed — retry as plain text
                    if "can't parse entities" in str(exc).lower():
                        plain = re.sub(r'\\(.)', r'\1', chunk)
                        sent = await self._app.bot.send_message(
                            chat_id=int(chat_id),
                            text=plain,
                            **kwargs,
                        )
                    else:
                        raise

            return SendResult(
                success=True,
                message_id=str(sent.message_id) if sent else None,
            )
        except Exception as e:
            logger.error("[telegram] Send failed to %s: %s", chat_id, e)
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str) -> None:
        if self._app and self._app.bot:
            try:
                await self._app.bot.send_chat_action(
                    chat_id=int(chat_id), action="typing",
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _should_process(self, message, is_command: bool = False) -> bool:
        """Apply policy checks."""
        chat = message.chat
        user = message.from_user
        if not user:
            return False

        chat_type = "group" if chat.type in ("group", "supergroup") else "dm"
        uid = str(user.id)

        if chat_type == "group":
            if self._group_policy == "disabled":
                return False
            if self._group_policy == "allowlist" and uid not in self._allow_from:
                return False
            # In groups, only process if bot is @mentioned or it's a command
            if not is_command:
                text = message.text or message.caption or ""
                bot_username = getattr(self._app.bot, '_bot_username', None)
                if not bot_username and self._app and self._app.bot:
                    # We can't easily get username here — allow through
                    pass
        else:
            if self._dm_policy == "disabled":
                return False
            if self._dm_policy == "allowlist" and uid not in self._allow_from:
                return False

        return True

    def _build_imessage(self, update: Update) -> IMessage:
        msg = update.message
        chat = msg.chat
        user = msg.from_user
        chat_type = "group" if chat.type in ("group", "supergroup") else "dm"
        text = msg.text or msg.caption or ""

        # Resolve thread_id for forum topics
        thread_id = None
        if msg.message_thread_id and str(msg.message_thread_id) != "1":
            thread_id = str(msg.message_thread_id)

        # Resolve reply context
        reply_to = None
        reply_to_text = None
        if msg.reply_to_message:
            reply_to = str(msg.reply_to_message.message_id)
            reply_to_text = msg.reply_to_message.text or msg.reply_to_message.caption

        return IMessage(
            platform="telegram",
            chat_id=str(chat.id),
            chat_type=chat_type,
            user_id=str(user.id) if user else "unknown",
            user_name=user.full_name or user.username or str(user.id) if user else "unknown",
            content=text,
            message_id=str(msg.message_id),
            thread_id=thread_id,
            reply_to=reply_to,
            reply_to_text=reply_to_text,
            raw_payload=msg,
        )

    async def _download_media(self, message, msg: IMessage) -> None:
        """Download media attachments to local cache files."""
        try:
            cache_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
                "history", "media_cache",
            )
            os.makedirs(cache_dir, exist_ok=True)

            file_obj = None
            ext = ".bin"
            if message.photo:
                file_obj = message.photo[-1]  # largest size
                ext = ".jpg"
            elif message.video:
                file_obj = message.video
                ext = ".mp4"
            elif message.audio:
                file_obj = message.audio
                ext = ".mp3"
            elif message.voice:
                file_obj = message.voice
                ext = ".ogg"
            elif message.document:
                file_obj = message.document
                name = message.document.file_name or "document"
                ext = os.path.splitext(name)[1] or ".bin"

            if file_obj and self._app:
                f = await file_obj.get_file()
                path = os.path.join(cache_dir, f"{file_obj.file_unique_id}{ext}")
                await f.download_to_drive(path)
                msg.media_urls.append(path)
                if message.photo:
                    msg.media_types.append("image/jpeg")
                elif message.video:
                    msg.media_types.append("video/mp4")
                elif message.audio:
                    msg.media_types.append("audio/mpeg")
                elif message.voice:
                    msg.media_types.append("audio/ogg")
                else:
                    msg.media_types.append("application/octet-stream")

        except Exception as e:
            logger.warning("[telegram] Media download failed: %s", e)

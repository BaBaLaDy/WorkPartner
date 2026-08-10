"""IM notification tools — proactive message push to the user.

Reads credentials from env vars; no bridge dependency.

Env vars:
    FEISHU_APP_ID        Bot App ID
    FEISHU_APP_SECRET    Bot App Secret
    FEISHU_MY_OPEN_ID    Your personal Feishu open_id (ou_xxx), used as default target

config.yaml:
    im:
      targets:
        me: "ou_xxx"       # DM to yourself
        team: "oc_xxx"     # group chat
"""

import asyncio
import json
import logging
import os

logger = logging.getLogger(__name__)

_feishu_client = None


def _get_feishu_client():
    global _feishu_client
    if _feishu_client is not None:
        return _feishu_client
    try:
        import lark_oapi as lark
        _feishu_client = (
            lark.Client.builder()
            .app_id(os.getenv("FEISHU_APP_ID", ""))
            .app_secret(os.getenv("FEISHU_APP_SECRET", ""))
            .log_level(lark.LogLevel.WARNING)
            .build()
        )
        return _feishu_client
    except ImportError:
        raise RuntimeError("lark-oapi not installed. Run: pip install lark-oapi")


def _resolve_target(target: str) -> tuple[str, str]:
    """Return (receive_id, receive_id_type) for a named target or raw ID.

    Resolution order:
    1. config.yaml im.targets[target]
    2. FEISHU_MY_OPEN_ID env var (when target == "me")
    3. Treat target as a raw receive_id if it starts with ou_ or oc_
    """
    from src.providers.factory import load_config
    config = load_config()
    targets: dict = config.get("im", {}).get("targets", {})

    raw_id = targets.get(target, "")

    # Expand env var references like "${FEISHU_MY_OPEN_ID}"
    if raw_id.startswith("${") and raw_id.endswith("}"):
        var = raw_id[2:-1]
        raw_id = os.getenv(var, "")

    # Fallback: "me" with no config → read env directly
    if not raw_id and target == "me":
        raw_id = os.getenv("FEISHU_MY_OPEN_ID", "").strip()

    # Fallback: caller passed a raw id directly
    if not raw_id and (target.startswith("ou_") or target.startswith("oc_")):
        raw_id = target

    if not raw_id:
        available = list(targets.keys()) or ["me"]
        raise ValueError(f"Target '{target}' not found. Available: {available}")

    # Determine receive_id_type from prefix
    if raw_id.startswith("oc_"):
        return raw_id, "chat_id"   # group chat
    else:
        return raw_id, "open_id"   # DM / user open_id


async def im_notify(message: str, target: str = "me") -> str:
    """向飞书发送通知消息，支持私信和群聊。任务完成、提醒、定时播报时使用。

    Args:
        message (str): 要发送的通知内容
        target (str): 发送目标，默认 "me"（私信自己）；群聊用 config.yaml 里配置的名称，如 "team"
    """
    try:
        receive_id, receive_id_type = _resolve_target(target)
    except ValueError as e:
        return f"Error: {e}"

    try:
        from lark_oapi.api.im.v1 import (
            CreateMessageRequest,
            CreateMessageRequestBody,
        )

        client = _get_feishu_client()
        payload = json.dumps({"text": message}, ensure_ascii=False)

        body = (
            CreateMessageRequestBody.builder()
            .receive_id(receive_id)
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

        resp = await asyncio.to_thread(client.im.v1.message.create, req)

        if resp and resp.success():
            logger.info("[im_notify] Sent to %s (%s)", target, receive_id_type)
            return f"通知已发送 → {target}"
        else:
            err = getattr(resp, "msg", "unknown error")
            code = getattr(resp, "code", -1)
            logger.warning("[im_notify] Send failed: code=%s msg=%s", code, err)
            return f"发送失败: {err} (code={code})"

    except Exception as e:
        logger.exception("[im_notify] Unexpected error")
        return f"Error: {e}"

"""Chat endpoint with streaming response."""

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.api.schemas import ChatMessageRequest
from src.core.engine import WorkPartnerEngine

router = APIRouter(prefix="/chat", tags=["chat"])


def get_engine() -> WorkPartnerEngine:
    from src.api.server import get_app_state
    return get_app_state().engine


def _get_or_create_session(engine: WorkPartnerEngine):
    """Get the interactive chat session, creating via Engine if needed."""
    if not hasattr(engine, "_chat_session"):
        engine._chat_session = engine.create_interactive_session(owner="ui")
        # Start MCP for the chat session (async, fire-and-forget)
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(engine._chat_session.start_mcp())
        except RuntimeError:
            pass
    return engine._chat_session


@router.post("")
async def send_message(body: ChatMessageRequest):
    """Send a chat message and receive a streaming SSE response."""
    engine = get_engine()
    session = _get_or_create_session(engine)

    from src.agent.session import build_system_prompt
    system_prompt = build_system_prompt(
        session.injector, body.message,
        memory_manager=session._memory_manager,
    )

    async def event_generator():
        async for event in session.stream_events(
            user_message=body.message,
            system_prompt=system_prompt,
            thread_id=body.thread_id,
        ):
            evt_type = event.get("event", "")
            data = event.get("data", "")
            if evt_type == "text_delta" and data:
                yield f"data: {json.dumps({'type': 'text', 'content': data})}\n\n"
            elif evt_type == "tool_input" and data:
                yield f"data: {json.dumps({'type': 'tool_start', 'data': data})}\n\n"
            elif evt_type == "tool_output" and data:
                yield f"data: {json.dumps({'type': 'tool_end', 'data': data})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

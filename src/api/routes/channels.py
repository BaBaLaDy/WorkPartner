"""IM channel management endpoints."""

from fastapi import APIRouter

from src.core.engine import WorkPartnerEngine

router = APIRouter(prefix="/channels", tags=["channels"])


def get_engine() -> WorkPartnerEngine:
    from src.api.server import get_app_state
    return get_app_state().engine


@router.get("")
async def list_channels():
    """List all configured IM channels and their status."""
    engine = get_engine()
    return {"channels": engine.list_channels()}


@router.post("/{name}/connect")
async def connect_channel(name: str):
    """Connect an IM channel by name."""
    engine = get_engine()
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_until_complete(engine.connect_channel(name))
    except RuntimeError:
        result = await engine.connect_channel(name)

    if result:
        return {"status": "connected", "channel": name}
    else:
        return {"status": "failed", "channel": name, "error": "Connection failed or no config available"}


@router.post("/{name}/disconnect")
async def disconnect_channel(name: str):
    """Disconnect an IM channel by name."""
    engine = get_engine()
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_until_complete(engine.disconnect_channel(name))
    except RuntimeError:
        result = await engine.disconnect_channel(name)

    if result:
        return {"status": "disconnected", "channel": name}
    else:
        return {"status": "failed", "channel": name, "error": "Adapter not connected"}

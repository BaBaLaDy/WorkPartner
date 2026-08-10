"""FastAPI application — entry point for the web API server."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.websocket import ConnectionManager
from src.core.engine import WorkPartnerEngine

logger = logging.getLogger(__name__)


@dataclass
class AppState:
    """Global application state shared across routes."""
    engine: WorkPartnerEngine | None = None
    ws_manager: ConnectionManager = field(default_factory=ConnectionManager)


_app_state = AppState()


def get_app_state() -> AppState:
    return _app_state


def create_app(engine: WorkPartnerEngine, dev_mode: bool = True,
               skip_lifespan_startup: bool = False) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        engine: The WorkPartnerEngine instance to expose via API.
        dev_mode: If True, enable CORS for Vite dev server (localhost:5173).
        skip_lifespan_startup: If True, don't start engine services in lifespan
            (caller is responsible for starting them).
    """
    _app_state.engine = engine
    _app_state.ws_manager = ConnectionManager()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not skip_lifespan_startup:
            # Start engine background services (scheduler + executor)
            logger.info("FastAPI lifespan: starting engine background services")
            engine.start_background()
            # Start the executor as an async task
            executor_task = asyncio.create_task(engine.start_async())
            
            # Start MCP manager (initialises task group for runtime connections)
            logger.info("FastAPI lifespan: starting MCP manager")
            await engine.start_mcp()

            logger.info("FastAPI lifespan: subscribing to EventBus")
            _app_state.ws_manager.subscribe_to_event_bus(engine.event_bus)
            _subscribe_cache_invalidation(engine)
            try:
                yield
            finally:
                logger.info("FastAPI lifespan: shutting down engine")
                executor_task.cancel()
                try:
                    await executor_task
                except asyncio.CancelledError:
                    pass
                await engine.stop()
        else:
            # Engine already started by caller — just subscribe to events
            logger.info("FastAPI lifespan: engine already started, subscribing to EventBus")
            _app_state.ws_manager.subscribe_to_event_bus(engine.event_bus)
            try:
                yield
            finally:
                logger.info("FastAPI lifespan: API server shutting down")

    app = FastAPI(
        title="WorkPartner API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS for development mode — restricted to local dev origins.
    # The API has no authentication; never expose it beyond localhost.
    if dev_mode:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:8000",
                "http://127.0.0.1:8000",
            ],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # -- Import and mount routes --
    from src.api.routes.tasks import router as tasks_router
    from src.api.routes.schedules import router as schedules_router
    from src.api.routes.chat import router as chat_router
    from src.api.routes.sessions import router as sessions_router
    from src.api.routes.status import router as status_router
    from src.api.routes.roles import router as roles_router
    from src.api.routes.channels import router as channels_router
    from src.api.routes.executor import router as executor_router
    from src.api.routes.supervisor import router as supervisor_router
    from src.api.routes.office_state import router as office_state_router
    from src.api.routes.office_state import _subscribe_cache_invalidation
    from src.api.routes.pins import router as pins_router
    from src.api.routes.skills import router as skills_router
    from src.api.routes.mcp import router as mcp_router

    app.include_router(tasks_router, prefix="/api")
    app.include_router(schedules_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(sessions_router, prefix="/api")
    app.include_router(status_router, prefix="/api")
    app.include_router(roles_router, prefix="/api")
    app.include_router(channels_router, prefix="/api")
    app.include_router(executor_router, prefix="/api")
    app.include_router(supervisor_router, prefix="/api")
    app.include_router(office_state_router, prefix="/api")
    app.include_router(pins_router, prefix="/api")
    app.include_router(skills_router, prefix="/api")
    app.include_router(mcp_router, prefix="/api")

    # -- WebSocket endpoint --
    @app.websocket("/ws/events")
    async def websocket_endpoint(ws: WebSocket):
        await _app_state.ws_manager.connect(ws)
        try:
            while True:
                # Keep connection alive — client can send ping
                await ws.receive_text()
        except WebSocketDisconnect:
            _app_state.ws_manager.disconnect(ws)
        except Exception:
            _app_state.ws_manager.disconnect(ws)

    # -- Serve static files in production --
    static_dir = Path(__file__).parent.parent / "frontend" / "web" / "dist"
    if not dev_mode and static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


def create_uvicorn_server(engine: WorkPartnerEngine, host: str = "0.0.0.0",
                          port: int = 8000, dev_mode: bool = True,
                          skip_lifespan_startup: bool = False):
    """Create a controllable uvicorn Server instance."""
    import uvicorn

    app = create_app(engine, dev_mode=dev_mode,
                     skip_lifespan_startup=skip_lifespan_startup)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    return uvicorn.Server(config)


def run_api_server(engine: WorkPartnerEngine, host: str = "0.0.0.0",
                   port: int = 8000, dev_mode: bool = True,
                   skip_lifespan_startup: bool = False):
    """Start the uvicorn server (blocking).

    Args:
        engine: The WorkPartnerEngine instance.
        host: Bind address.
        port: Bind port.
        dev_mode: Enable CORS.
        skip_lifespan_startup: If True, caller must start engine services.
    """
    logger.info("Starting API server on %s:%d (dev=%s)", host, port, dev_mode)
    server = create_uvicorn_server(
        engine, host=host, port=port, dev_mode=dev_mode,
        skip_lifespan_startup=skip_lifespan_startup,
    )
    server.run()

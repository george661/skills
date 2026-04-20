"""FastAPI server for dag-dashboard."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Dict, Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .broadcast import Broadcaster
from .chat_relay import ChatRelay
from .chat_routes import create_chat_router
from .checkpoint_routes import router as checkpoint_router
from .config import Settings
from .database import ensure_dir, init_db
from .event_collector import EventCollector
from .notifier import SlackNotifier
from .sse import create_sse_router
from .routes import router
from .trigger import create_trigger_router

logger = logging.getLogger(__name__)


def create_app(
    db_dir: Optional[Path] = None,
    db_path: Optional[Path] = None,
    events_dir: Path = Path("dag-events"),
    pipe_root: Optional[Path] = None,
    max_sse_connections: int = 50,
    slack_notifier: Optional[SlackNotifier] = None,
    dashboard_url: str = "http://127.0.0.1:8100",
    checkpoint_prefix: Optional[Path] = None,
    settings: Optional[Settings] = None,
    checkpoint_dir_fallback: Optional[str] = None,
) -> FastAPI:
    """Create and configure FastAPI application."""

    # Initialize database first (before creating app)
    if db_path is None:
        if db_dir is None:
            raise ValueError("Either db_dir or db_path must be provided")
        ensure_dir(db_dir)
        db_path = db_dir / "dashboard.db"
    init_db(db_path)

    # Ensure events directory exists
    ensure_dir(events_dir)

    # Set default pipe_root
    if pipe_root is None:
        pipe_root = Path.home() / ".dag-dashboard" / "chat"

    # Create broadcaster
    broadcaster = Broadcaster()

    # Create chat relay
    chat_relay = ChatRelay(db_path=db_path, pipe_root=pipe_root)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Initialize event collector on startup."""
        # Store broadcaster, db_path, chat_relay, and checkpoint_dir_fallback in app.state for access by endpoints/tests
        app.state.broadcaster = broadcaster
        app.state.db_path = db_path
        app.state.db_dir = db_dir if db_dir else db_path.parent
        app.state.events_dir = events_dir
        app.state.chat_relay = chat_relay
        app.state.checkpoint_dir_fallback = checkpoint_dir_fallback

        # Create and start event collector
        loop = asyncio.get_running_loop()
        collector = EventCollector(
            events_dir=events_dir,
            db_path=db_path,
            broadcaster=broadcaster,
            loop=loop,
            slack_notifier=slack_notifier,
            dashboard_url=dashboard_url,
        )
        collector.start()
        app.state.collector = collector

        logger.info(f"Event collector started, watching {events_dir}")
        logger.info(f"Chat relay initialized, pipe_root: {pipe_root}")

        yield

        # Shutdown: stop collector and chat relay
        collector.stop()
        chat_relay.stop()
        logger.info("Event collector and chat relay stopped")

    app = FastAPI(
        title="DAG Dashboard",
        description="Workflow execution monitoring dashboard",
        version="0.1.0",
        lifespan=lifespan
    )

    # Store db_dir, events_dir, and checkpoint state in app state for lifespan and route access
    app.state.db_dir = db_dir
    app.state.events_dir = events_dir
    app.state.checkpoint_prefix = checkpoint_prefix
    app.state.checkpoint_dir_fallback = checkpoint_dir_fallback

    # Register routes
    app.include_router(router)

    # Register checkpoint routes if checkpoint_prefix is set
    if checkpoint_prefix is not None:
        app.include_router(checkpoint_router)

    # Register chat routes
    chat_router = create_chat_router(db_path)
    app.include_router(chat_router)

    # Mount static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/css", StaticFiles(directory=str(static_dir / "css")), name="css")
        app.mount("/js", StaticFiles(directory=str(static_dir / "js")), name="js")

    @app.get("/health")
    async def health() -> Dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok"}

    @app.get("/")
    async def root() -> FileResponse:
        """Serve index.html at root path."""
        static_dir = Path(__file__).parent / "static"
        index_path = static_dir / "index.html"
        if not index_path.exists():
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="index.html not found")
        return FileResponse(index_path)

    # Mount SSE router - router has its own state, doesn't need app.state
    sse_router = create_sse_router(
        db_path=db_path,
        broadcaster=broadcaster,
        max_connections=max_sse_connections
    )
    app.include_router(sse_router)

    # Mount trigger router if enabled
    if settings and settings.trigger_enabled:
        trigger_router = create_trigger_router(settings, db_path)
        app.include_router(trigger_router)
        logger.info("Trigger endpoint enabled")

    return app

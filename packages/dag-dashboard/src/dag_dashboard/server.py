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
from .database import ensure_dir, init_db
from .event_collector import EventCollector
from .notifier import SlackNotifier
from .sse import create_sse_router
from .routes import router

logger = logging.getLogger(__name__)


def create_app(
    db_dir: Path,
    events_dir: Path = Path("dag-events"),
    max_sse_connections: int = 50,
    slack_notifier: Optional[SlackNotifier] = None,
    dashboard_url: str = "http://127.0.0.1:8100",
) -> FastAPI:
    """Create and configure FastAPI application."""

    # Initialize database first (before creating app)
    ensure_dir(db_dir)
    db_path = db_dir / "dashboard.db"
    init_db(db_path)

    # Ensure events directory exists
    ensure_dir(events_dir)

    # Create broadcaster
    broadcaster = Broadcaster()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Initialize event collector on startup."""
        # Store broadcaster and db_path in app.state for access by endpoints/tests
        app.state.broadcaster = broadcaster
        app.state.db_path = db_path

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

        yield

        # Shutdown: stop collector
        collector.stop()
        logger.info("Event collector stopped")

    app = FastAPI(
        title="DAG Dashboard",
        description="Workflow execution monitoring dashboard",
        version="0.1.0",
        lifespan=lifespan
    )

    # Store db_dir and events_dir in app state for lifespan and route access
    app.state.db_dir = db_dir
    app.state.events_dir = events_dir

    # Register routes
    app.include_router(router)

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

    return app

"""FastAPI server for dag-dashboard."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Dict

from fastapi import FastAPI

from .broadcast import Broadcaster
from .database import ensure_dir, init_db
from .event_collector import EventCollector
from .sse import create_sse_router
from .routes import router

logger = logging.getLogger(__name__)


def create_app(db_dir: Path, events_dir: Path = Path("dag-events"), max_sse_connections: int = 50) -> FastAPI:
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
            loop=loop
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

    # Store db_dir in app state for lifespan and route access
    app.state.db_dir = db_dir

    # Register routes
    app.include_router(router)

    @app.get("/health")
    async def health() -> Dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok"}

    # Mount SSE router - router has its own state, doesn't need app.state
    sse_router = create_sse_router(
        db_path=db_path,
        broadcaster=broadcaster,
        max_connections=max_sse_connections
    )
    app.include_router(sse_router)

    return app

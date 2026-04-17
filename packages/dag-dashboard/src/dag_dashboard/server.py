"""FastAPI server for dag-dashboard."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from .broadcast import Broadcaster
from .database import ensure_dir, init_db
from .event_collector import EventCollector
from .sse import _get_persisted_events

logger = logging.getLogger(__name__)


def create_app(db_dir: Path, events_dir: Path = Path("dag-events"), max_sse_connections: int = 50) -> FastAPI:
    """Create and configure FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Initialize database, event collector, and broadcaster on startup."""
        # Initialize database
        ensure_dir(db_dir)
        db_path = db_dir / "dashboard.db"
        init_db(db_path)

        # Ensure events directory exists
        ensure_dir(events_dir)

        # Create broadcaster
        broadcaster = Broadcaster()
        app.state.broadcaster = broadcaster
        app.state.db_path = db_path
        app.state.connection_counts = {}
        app.state.counts_lock = asyncio.Lock()

        # Create and start event collector
        loop = asyncio.get_event_loop()
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

    @app.get("/health")
    async def health() -> Dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok"}

    @app.get("/api/workflows/{run_id}/events")
    async def stream_events(run_id: str, request: Request) -> StreamingResponse:
        """
        Stream workflow events via SSE.

        First replays persisted events from SQLite, then streams live events.
        Enforces max_connections limit per run_id.
        """
        broadcaster = app.state.broadcaster
        db_path = app.state.db_path
        connection_counts = app.state.connection_counts
        counts_lock = app.state.counts_lock

        # Check connection limit
        async with counts_lock:
            current_count = connection_counts.get(run_id, 0)
            if current_count >= max_sse_connections:
                raise HTTPException(
                    status_code=503,
                    detail=f"Maximum {max_sse_connections} SSE connections reached for run {run_id}"
                )
            connection_counts[run_id] = current_count + 1

        async def event_stream() -> AsyncIterator[str]:
            """Generate SSE event stream."""
            try:
                # Phase 1: Replay persisted events from SQLite
                loop = asyncio.get_event_loop()
                replayed_events = await loop.run_in_executor(
                    None,
                    _get_persisted_events,
                    db_path,
                    run_id
                )

                for event in replayed_events:
                    yield f"data: {json.dumps(event)}\n\n"

                # Phase 2: Stream live events from broadcaster
                async with broadcaster.subscribe(run_id) as queue:
                    while True:
                        # Check if client disconnected
                        if await request.is_disconnected():
                            logger.info(f"Client disconnected from SSE stream for run {run_id}")
                            break

                        # Get next event with timeout
                        try:
                            event = await asyncio.wait_for(queue.get(), timeout=1.0)
                            yield f"data: {json.dumps(event)}\n\n"
                        except asyncio.TimeoutError:
                            # Send keepalive comment
                            yield ": keepalive\n\n"
                            continue

            finally:
                # Decrement connection count on disconnect
                async with counts_lock:
                    connection_counts[run_id] = connection_counts.get(run_id, 1) - 1
                    if connection_counts[run_id] <= 0:
                        connection_counts.pop(run_id, None)
                logger.info(f"SSE connection closed for run {run_id}")

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no"
            }
        )

    return app

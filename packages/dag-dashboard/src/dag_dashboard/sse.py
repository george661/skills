"""SSE endpoint for streaming workflow events."""
import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, AsyncIterator, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .broadcast import Broadcaster

logger = logging.getLogger(__name__)


def create_sse_router(
    db_path: Path,
    broadcaster: Broadcaster,
    max_connections: int = 50
) -> APIRouter:
    """
    Create SSE router with connection management.
    
    Args:
        db_path: Path to SQLite database
        broadcaster: Broadcaster instance for live events
        max_connections: Maximum SSE connections per run_id
    
    Returns:
        Configured FastAPI router
    """
    router = APIRouter()
    
    # Track connections per run_id
    connection_counts: Dict[str, int] = {}
    counts_lock = asyncio.Lock()
    
    @router.get("/api/workflows/{run_id}/events")
    async def stream_events(run_id: str, request: Request) -> StreamingResponse:
        """
        Stream workflow events via SSE.
        
        First replays persisted events from SQLite, then streams live events.
        Enforces max_connections limit per run_id.
        """
        # Check connection limit
        async with counts_lock:
            current_count = connection_counts.get(run_id, 0)
            if current_count >= max_connections:
                raise HTTPException(
                    status_code=503,
                    detail=f"Maximum {max_connections} SSE connections reached for run {run_id}"
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
    
    return router


def _get_persisted_events(db_path: Path, run_id: str) -> list[Dict[str, Any]]:
    """
    Retrieve persisted events from SQLite (sync function for run_in_executor).
    
    Returns events in chronological order.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(
            """
            SELECT event_type, payload, created_at
            FROM events
            WHERE run_id = ?
            ORDER BY created_at ASC
            """,
            (run_id,)
        )
        
        events = []
        for row in cursor.fetchall():
            events.append({
                "event_type": row["event_type"],
                "payload": row["payload"],
                "created_at": row["created_at"]
            })
        
        return events
    finally:
        conn.close()

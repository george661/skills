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
    router = APIRouter()

    connection_counts: Dict[str, int] = {}
    counts_lock = asyncio.Lock()

    @router.get("/api/workflows/{run_id}/events")
    async def stream_events(run_id: str, request: Request) -> StreamingResponse:
        async with counts_lock:
            current_count = connection_counts.get(run_id, 0)
            if current_count >= max_connections:
                raise HTTPException(
                    status_code=503,
                    detail=f"Maximum {max_connections} SSE connections reached for run {run_id}"
                )
            connection_counts[run_id] = current_count + 1

        async def event_stream() -> AsyncIterator[str]:
            try:
                loop = asyncio.get_event_loop()
                replayed_events = await loop.run_in_executor(
                    None,
                    get_persisted_events,
                    db_path,
                    run_id
                )

                for event in replayed_events:
                    yield f"data: {json.dumps(event)}\n\n"

                async with broadcaster.subscribe(run_id) as queue:
                    while True:
                        try:
                            if await request.is_disconnected():
                                break
                        except Exception:
                            break

                        try:
                            event = await asyncio.wait_for(queue.get(), timeout=1.0)
                            yield f"data: {json.dumps(event)}\n\n"
                        except asyncio.TimeoutError:
                            yield ": keepalive\n\n"
                        except (asyncio.CancelledError, GeneratorExit):
                            break

            except (asyncio.CancelledError, GeneratorExit):
                pass
            finally:
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


def get_persisted_events(db_path: Path, run_id: str) -> list[Dict[str, Any]]:
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

"""SSE endpoint for streaming workflow events."""
import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional

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

    @router.get("/api/workflows/{run_id}/logs/stream")
    async def stream_logs(
        run_id: str,
        request: Request,
        node: Optional[str] = None,
        stream: str = "all"
    ) -> StreamingResponse:
        # Validate stream parameter
        if stream not in ("all", "stdout", "stderr"):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid stream filter: {stream}. Must be 'all', 'stdout', or 'stderr'"
            )

        async with counts_lock:
            current_count = connection_counts.get(run_id, 0)
            if current_count >= max_connections:
                raise HTTPException(
                    status_code=503,
                    detail=f"Maximum {max_connections} SSE connections reached for run {run_id}"
                )
            connection_counts[run_id] = current_count + 1

        # Terminal events that should close the stream
        _TERMINAL_EVENTS = {
            "workflow_completed",
            "workflow_failed",
            "workflow_cancelled",
            "workflow_interrupted",
        }

        async def log_stream() -> AsyncIterator[str]:
            try:
                loop = asyncio.get_event_loop()
                replayed_logs = await loop.run_in_executor(
                    None,
                    get_persisted_node_log_lines,
                    db_path,
                    run_id,
                    node,
                    stream
                )

                for event in replayed_logs:
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

                            # Check for terminal events
                            event_type = event.get("event_type")
                            if event_type in _TERMINAL_EVENTS:
                                yield f"data: {json.dumps(event)}\n\n"
                                break

                            # Filter for node_log_line events only
                            if event_type != "node_log_line":
                                continue

                            # Apply node filter if set
                            if node:
                                payload_str = event.get("payload", "{}")
                                try:
                                    payload = json.loads(payload_str) if isinstance(payload_str, str) else payload_str
                                    if payload.get("node_id") != node:
                                        continue
                                except (json.JSONDecodeError, KeyError):
                                    continue

                            # Apply stream filter if not "all"
                            if stream != "all":
                                payload_str = event.get("payload", "{}")
                                try:
                                    payload = json.loads(payload_str) if isinstance(payload_str, str) else payload_str
                                    metadata = payload.get("metadata", {})
                                    if metadata.get("stream") != stream:
                                        continue
                                except (json.JSONDecodeError, KeyError):
                                    continue

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
                logger.info(f"SSE logs connection closed for run {run_id}")

        return StreamingResponse(
            log_stream(),
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


def get_persisted_node_log_lines(
    db_path: Path,
    run_id: str,
    node_filter: Optional[str] = None,
    stream_filter: str = "all"
) -> list[Dict[str, Any]]:
    """Get persisted node_log_line events with optional filters."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(
            """
            SELECT event_type, payload, created_at
            FROM events
            WHERE run_id = ? AND event_type = 'node_log_line'
            ORDER BY created_at ASC
            """,
            (run_id,)
        )

        events = []
        for row in cursor.fetchall():
            event = {
                "event_type": row["event_type"],
                "payload": row["payload"],
                "created_at": row["created_at"]
            }

            # Apply filters if needed
            if node_filter or stream_filter != "all":
                try:
                    payload = json.loads(row["payload"])

                    # Node filter
                    if node_filter and payload.get("node_id") != node_filter:
                        continue

                    # Stream filter
                    if stream_filter != "all":
                        metadata = payload.get("metadata", {})
                        if metadata.get("stream") != stream_filter:
                            continue
                except (json.JSONDecodeError, KeyError):
                    continue

            events.append(event)

        return events
    finally:
        conn.close()

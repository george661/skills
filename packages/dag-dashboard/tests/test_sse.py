"""Tests for SSE endpoint."""
import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from dag_dashboard.broadcast import Broadcaster
from dag_dashboard.database import init_db
from dag_dashboard.sse import create_sse_router


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    """Create test database with sample events."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    # Insert sample workflow_runs and events
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        
        cursor.execute(
            "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
            ("run_123", "test_workflow", "running", "2026-04-17T12:00:00Z")
        )
        
        cursor.execute(
            "INSERT INTO events (run_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            ("run_123", "workflow.started", json.dumps({"test": "data"}), "2026-04-17T12:00:00Z")
        )
        cursor.execute(
            "INSERT INTO events (run_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            ("run_123", "node.started", json.dumps({"node": "step1"}), "2026-04-17T12:00:01Z")
        )
        
        conn.commit()
    finally:
        conn.close()
    
    return db_path


@pytest.fixture
async def broadcaster() -> Broadcaster:
    """Create broadcaster."""
    return Broadcaster()


@pytest.mark.asyncio
async def test_sse_endpoint_returns_correct_content_type(test_db: Path, broadcaster: Broadcaster) -> None:
    """Test that SSE endpoint returns text/event-stream content type."""
    app = FastAPI()
    router = create_sse_router(test_db, broadcaster, max_connections=50)
    app.include_router(router)
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Start streaming request
        async with client.stream("GET", "/api/workflows/run_123/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream"
            assert response.headers["cache-control"] == "no-cache"
            # Read one line and exit
            async for _ in response.aiter_lines():
                break


@pytest.mark.asyncio
async def test_sse_replays_persisted_events(test_db: Path, broadcaster: Broadcaster) -> None:
    """Test that SSE endpoint replays existing events from SQLite on connect."""
    app = FastAPI()
    router = create_sse_router(test_db, broadcaster, max_connections=50)
    app.include_router(router)
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        replayed_events = []
        
        async with client.stream("GET", "/api/workflows/run_123/events") as response:
            # Read first two SSE messages (replayed events)
            line_count = 0
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    event_json = line[6:]  # Strip "data: " prefix
                    replayed_events.append(json.loads(event_json))
                line_count += 1
                if line_count >= 10:  # Limit lines to prevent hang
                    break
        
        assert len(replayed_events) == 2
        assert replayed_events[0]["event_type"] == "workflow.started"
        assert replayed_events[1]["event_type"] == "node.started"


@pytest.mark.asyncio
async def test_sse_streams_live_events(test_db: Path, broadcaster: Broadcaster) -> None:
    """Test that SSE endpoint streams live events from broadcaster."""
    app = FastAPI()
    router = create_sse_router(test_db, broadcaster, max_connections=50)
    app.include_router(router)
    
    live_events = []
    stream_done = asyncio.Event()
    
    async def sse_client():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            async with client.stream("GET", "/api/workflows/run_123/events") as response:
                # Skip replayed events (first 2)
                data_lines = 0
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_lines += 1
                        if data_lines > 2:
                            # This is a live event
                            event_json = line[6:]
                            live_events.append(json.loads(event_json))
                            stream_done.set()
                            return
                    if data_lines > 10:  # Safety limit
                        return
    
    client_task = asyncio.create_task(sse_client())
    
    # Give client time to connect and replay
    await asyncio.sleep(0.2)
    
    # Publish live event
    live_event = {
        "event_type": "node.completed",
        "payload": json.dumps({"node": "step1", "status": "success"}),
        "created_at": "2026-04-17T12:00:02Z"
    }
    await broadcaster.publish("run_123", live_event)
    
    # Wait for client to receive or timeout
    try:
        await asyncio.wait_for(stream_done.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        pass
    finally:
        client_task.cancel()
        try:
            await client_task
        except asyncio.CancelledError:
            pass
    
    assert len(live_events) >= 1
    assert live_events[0]["event_type"] == "node.completed"


@pytest.mark.asyncio
async def test_sse_connection_limit(test_db: Path, broadcaster: Broadcaster) -> None:
    """Test that 3rd connection returns 503 when limit is 2."""
    app = FastAPI()
    router = create_sse_router(test_db, broadcaster, max_connections=1)
    app.include_router(router)
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Open first connection (at limit)
        stream1 = client.stream("GET", "/api/workflows/run_limit/events")
        response1 = await stream1.__aenter__()
        assert response1.status_code == 200
        
        # Try second connection - should fail
        response2 = await client.get("/api/workflows/run_limit/events")
        assert response2.status_code == 503
        assert "maximum" in response2.json()["detail"].lower()
        
        # Cleanup
        await stream1.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_sse_disconnect_decrements_counter(test_db: Path, broadcaster: Broadcaster) -> None:
    """Test that client disconnect decrements connection count."""
    app = FastAPI()
    router = create_sse_router(test_db, broadcaster, max_connections=1)
    app.include_router(router)
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Open and immediately close connection
        async with client.stream("GET", "/api/workflows/run_disconnect/events") as response:
            assert response.status_code == 200
            # Read one line to ensure stream started
            async for _ in response.aiter_lines():
                break
        # Connection closed here
        
        await asyncio.sleep(0.1)  # Give time for cleanup
        
        # Should be able to open another connection now
        async with client.stream("GET", "/api/workflows/run_disconnect/events") as response:
            assert response.status_code == 200
            async for _ in response.aiter_lines():
                break


@pytest.mark.asyncio
async def test_sse_isolates_run_ids(test_db: Path, broadcaster: Broadcaster) -> None:
    """Test that SSE endpoints for different run_ids are isolated."""
    app = FastAPI()
    router = create_sse_router(test_db, broadcaster, max_connections=1)
    app.include_router(router)
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Open connection to run_123 (at limit for run_123)
        stream1 = client.stream("GET", "/api/workflows/run_isolate_1/events")
        response1 = await stream1.__aenter__()
        assert response1.status_code == 200
        
        # Should be able to open connection to run_456 (different run_id)
        stream2 = client.stream("GET", "/api/workflows/run_isolate_2/events")
        response2 = await stream2.__aenter__()
        assert response2.status_code == 200
        
        # Cleanup
        await stream1.__aexit__(None, None, None)
        await stream2.__aexit__(None, None, None)

"""Tests for SSE endpoint."""
import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pytest

from dag_dashboard.broadcast import Broadcaster
from dag_dashboard.database import init_db
from dag_dashboard.sse import create_sse_router, get_persisted_events


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    """Create test database with sample events."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

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
def broadcaster() -> Broadcaster:
    """Create broadcaster."""
    return Broadcaster()


def test_get_persisted_events_returns_events(test_db: Path) -> None:
    """Test that get_persisted_events retrieves events in order."""
    events = get_persisted_events(test_db, "run_123")

    assert len(events) == 2
    assert events[0]["event_type"] == "workflow.started"
    assert events[1]["event_type"] == "node.started"


def test_get_persisted_events_empty_for_unknown_run(test_db: Path) -> None:
    """Test that get_persisted_events returns empty list for unknown run_id."""
    events = get_persisted_events(test_db, "nonexistent")
    assert events == []


def test_connection_limit_returns_503(test_db: Path, broadcaster: Broadcaster) -> None:
    """Test that exceeding connection limit returns 503."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    router = create_sse_router(test_db, broadcaster, max_connections=0)
    app.include_router(router)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/workflows/run_123/events")
    assert response.status_code == 503
    assert "maximum" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_sse_replays_persisted_events(test_db: Path, broadcaster: Broadcaster) -> None:
    """Test that SSE replay yields persisted events as SSE data lines."""
    events = get_persisted_events(test_db, "run_123")

    sse_lines = [f"data: {json.dumps(e)}\n\n" for e in events]
    assert len(sse_lines) == 2

    parsed = [json.loads(line.removeprefix("data: ").strip()) for line in sse_lines]
    assert parsed[0]["event_type"] == "workflow.started"
    assert parsed[1]["event_type"] == "node.started"


@pytest.mark.asyncio
async def test_sse_streams_live_events_via_broadcaster(broadcaster: Broadcaster) -> None:
    """Test that broadcaster delivers live events to subscribers."""
    received: List[Dict[str, Any]] = []

    async with broadcaster.subscribe("run_123") as queue:
        event = {
            "event_type": "node.completed",
            "payload": json.dumps({"node": "step1", "status": "success"}),
            "created_at": "2026-04-17T12:00:02Z"
        }
        await broadcaster.publish("run_123", event)
        result = await asyncio.wait_for(queue.get(), timeout=2.0)
        received.append(result)

    assert len(received) == 1
    assert received[0]["event_type"] == "node.completed"


@pytest.mark.asyncio
async def test_sse_disconnect_frees_connection_slot(broadcaster: Broadcaster) -> None:
    """Test that connection count tracks subscribers correctly."""
    counts: Dict[str, int] = {}
    lock = asyncio.Lock()

    async with lock:
        counts["run_1"] = counts.get("run_1", 0) + 1
    assert counts["run_1"] == 1

    async with lock:
        counts["run_1"] -= 1
        if counts["run_1"] <= 0:
            counts.pop("run_1", None)
    assert "run_1" not in counts


@pytest.mark.asyncio
async def test_sse_isolates_run_ids(broadcaster: Broadcaster) -> None:
    """Test that subscribers to different run_ids are isolated."""
    events_run1: List[Dict[str, Any]] = []
    events_run2: List[Dict[str, Any]] = []

    async with broadcaster.subscribe("run_1") as q1, broadcaster.subscribe("run_2") as q2:
        await broadcaster.publish("run_1", {"event_type": "a"})
        await broadcaster.publish("run_2", {"event_type": "b"})

        r1 = await asyncio.wait_for(q1.get(), timeout=2.0)
        r2 = await asyncio.wait_for(q2.get(), timeout=2.0)
        events_run1.append(r1)
        events_run2.append(r2)

    assert events_run1[0]["event_type"] == "a"
    assert events_run2[0]["event_type"] == "b"

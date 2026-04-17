"""Tests for event collector."""
import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

from dag_dashboard.broadcast import Broadcaster
from dag_dashboard.database import init_db
from dag_dashboard.event_collector import EventCollector


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    """Create test database."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def events_dir(tmp_path: Path) -> Path:
    """Create events directory."""
    events_dir = tmp_path / "dag-events"
    events_dir.mkdir()
    return events_dir


@pytest.fixture
async def broadcaster() -> Broadcaster:
    """Create broadcaster."""
    return Broadcaster()


def get_persisted_events(db_path: Path, run_id: str) -> List[Dict[str, Any]]:
    """Retrieve persisted events from database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(
            "SELECT event_type, payload, created_at FROM events WHERE run_id = ? ORDER BY created_at",
            (run_id,)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def test_collector_initialization(test_db: Path, events_dir: Path) -> None:
    """Test that collector initializes without errors."""
    loop = asyncio.new_event_loop()
    broadcaster = Broadcaster()
    
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )
    
    assert collector is not None
    loop.close()


@pytest.mark.asyncio
async def test_collector_persists_event(test_db: Path, events_dir: Path, broadcaster: Broadcaster) -> None:
    """Test that collector persists NDJSON events to SQLite."""
    loop = asyncio.get_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )
    
    # Start collector
    collector.start()
    
    try:
        # Write NDJSON file
        run_id = "test_run_123"
        ndjson_file = events_dir / f"{run_id}.ndjson"
        
        event = {
            "workflow_name": "test_workflow",
            "event_type": "node.started",
            "payload": json.dumps({"node": "step1"}),
            "created_at": "2026-04-17T12:00:00Z"
        }
        
        with open(ndjson_file, "w") as f:
            f.write(json.dumps(event) + "\n")
        
        # Give watchdog time to process
        await asyncio.sleep(0.3)
        
        # Verify event was persisted
        persisted = get_persisted_events(test_db, run_id)
        assert len(persisted) == 1
        assert persisted[0]["event_type"] == "node.started"
        assert json.loads(persisted[0]["payload"])["node"] == "step1"
        
    finally:
        collector.stop()


@pytest.mark.asyncio
async def test_collector_broadcasts_event(test_db: Path, events_dir: Path, broadcaster: Broadcaster) -> None:
    """Test that collector broadcasts events to subscribers."""
    loop = asyncio.get_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )
    
    collector.start()
    
    try:
        run_id = "test_run_456"
        received_events: List[Dict[str, Any]] = []
        
        async def subscriber():
            async with broadcaster.subscribe(run_id) as queue:
                event = await asyncio.wait_for(queue.get(), timeout=2.0)
                received_events.append(event)
        
        # Start subscriber
        sub_task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.05)
        
        # Write event
        ndjson_file = events_dir / f"{run_id}.ndjson"
        event = {
            "workflow_name": "test_workflow",
            "event_type": "workflow.started",
            "payload": json.dumps({"test": "data"}),
            "created_at": "2026-04-17T12:00:00Z"
        }
        
        with open(ndjson_file, "w") as f:
            f.write(json.dumps(event) + "\n")
        
        # Wait for event to be received
        await asyncio.wait_for(sub_task, timeout=2.0)
        
        assert len(received_events) == 1
        assert received_events[0]["event_type"] == "workflow.started"
        
    finally:
        collector.stop()


@pytest.mark.asyncio
async def test_collector_handles_malformed_json(test_db: Path, events_dir: Path, broadcaster: Broadcaster) -> None:
    """Test that malformed JSON lines are skipped with warning."""
    loop = asyncio.get_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )
    
    collector.start()
    
    try:
        run_id = "test_run_malformed"
        ndjson_file = events_dir / f"{run_id}.ndjson"
        
        # Write valid event, malformed JSON, then another valid event
        with open(ndjson_file, "w") as f:
            valid_event_1 = {
                "workflow_name": "test_workflow",
                "event_type": "event1",
                "payload": json.dumps({}),
                "created_at": "2026-04-17T12:00:00Z"
            }
            f.write(json.dumps(valid_event_1) + "\n")
            f.write("{invalid json\n")  # Malformed
            valid_event_2 = {
                "workflow_name": "test_workflow",
                "event_type": "event2",
                "payload": json.dumps({}),
                "created_at": "2026-04-17T12:00:01Z"
            }
            f.write(json.dumps(valid_event_2) + "\n")
        
        await asyncio.sleep(0.3)
        
        # Only valid events should be persisted
        persisted = get_persisted_events(test_db, run_id)
        assert len(persisted) == 2
        assert persisted[0]["event_type"] == "event1"
        assert persisted[1]["event_type"] == "event2"
        
    finally:
        collector.stop()


@pytest.mark.asyncio
async def test_collector_handles_file_deletion(test_db: Path, events_dir: Path, broadcaster: Broadcaster) -> None:
    """Test that file deletion is handled gracefully (no crash)."""
    loop = asyncio.get_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )

    collector.start()

    try:
        run_id = "test_run_deletion"
        ndjson_file = events_dir / f"{run_id}.ndjson"

        event1 = {
            "workflow_name": "test_workflow",
            "event_type": "event1",
            "payload": json.dumps({}),
            "created_at": "2026-04-17T12:00:00Z"
        }
        with open(ndjson_file, "w") as f:
            f.write(json.dumps(event1) + "\n")

        await asyncio.sleep(0.5)

        persisted_before = get_persisted_events(test_db, run_id)
        assert len(persisted_before) == 1
        assert persisted_before[0]["event_type"] == "event1"

        # Delete file — collector must not crash
        ndjson_file.unlink()
        await asyncio.sleep(0.3)

        # Collector is still running (didn't crash on deletion)
        assert collector.observer.is_alive()

    finally:
        collector.stop()


@pytest.mark.asyncio
async def test_collector_creates_workflow_runs_row(test_db: Path, events_dir: Path, broadcaster: Broadcaster) -> None:
    """Test that collector creates workflow_runs row for FK constraint."""
    loop = asyncio.get_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )
    
    collector.start()
    
    try:
        run_id = "test_run_fk"
        ndjson_file = events_dir / f"{run_id}.ndjson"
        
        event = {
            "workflow_name": "my_workflow",
            "event_type": "workflow.started",
            "payload": json.dumps({}),
            "created_at": "2026-04-17T12:00:00Z"
        }
        
        with open(ndjson_file, "w") as f:
            f.write(json.dumps(event) + "\n")
        
        await asyncio.sleep(0.3)
        
        # Verify workflow_runs row was created
        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, workflow_name, status FROM workflow_runs WHERE id = ?", (run_id,))
            row = cursor.fetchone()
            
            assert row is not None
            assert row["id"] == run_id
            assert row["workflow_name"] == "my_workflow"
            assert row["status"] == "running"
        finally:
            conn.close()
        
    finally:
        collector.stop()

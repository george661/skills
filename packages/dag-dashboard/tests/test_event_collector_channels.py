"""Tests for channel event handling in EventCollector."""
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import Mock
import pytest

from dag_dashboard.event_collector import EventCollector
from dag_dashboard.database import init_db


@pytest.fixture
def setup_collector():
    """Create a temporary database and mock broadcaster."""
    import asyncio
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        events_dir = Path(tmpdir) / "events"
        events_dir.mkdir()

        init_db(db_path)

        # Create mock broadcaster and real loop
        broadcaster = Mock()
        async def mock_publish(run_id, event):
            pass
        broadcaster.publish = mock_publish

        # Use a real event loop for testing
        loop = asyncio.new_event_loop()

        collector = EventCollector(
            events_dir=events_dir,
            db_path=db_path,
            broadcaster=broadcaster,
            loop=loop
        )

        yield collector, db_path, events_dir

        loop.close()


def test_channel_updated_persists_to_db(setup_collector):
    """Handles channel_updated event → UPSERT into channel_states."""
    collector, db_path, events_dir = setup_collector
    
    run_id = "test-run-123"
    
    # Create workflow_runs row first
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
        (run_id, "test-workflow", "running", "2026-04-20T10:00:00Z")
    )
    conn.commit()
    conn.close()
    
    # Simulate channel_updated event
    event_data = {
        "workflow_id": run_id,
        "event_type": "channel_updated",
        "metadata": {
            "channel_key": "state_var",
            "channel_type": "LastValueChannel",
            "value": {"count": 42},
            "version": 1,
            "writer_node_id": "node_a"
        },
        "created_at": "2026-04-20T10:01:00Z"
    }
    
    collector._persist_and_broadcast(run_id, event_data)
    
    # Check that channel_states row was created
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT channel_key, channel_type, value_json, version, writers_json FROM channel_states WHERE run_id = ?",
        (run_id,)
    )
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row[0] == "state_var"
    assert row[1] == "LastValueChannel"
    assert json.loads(row[2]) == {"count": 42}
    assert row[3] == 1
    assert json.loads(row[4]) == ["node_a"]


def test_channel_updated_upserts_monotonic_version(setup_collector):
    """Second channel_updated event UPSERTs with incremented version."""
    collector, db_path, events_dir = setup_collector
    
    run_id = "test-run-456"
    
    # Create workflow_runs row
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
        (run_id, "test-workflow", "running", "2026-04-20T10:00:00Z")
    )
    conn.commit()
    conn.close()
    
    # First write
    collector._persist_and_broadcast(run_id, {
        "workflow_id": run_id,
        "event_type": "channel_updated",
        "metadata": {
            "channel_key": "counter",
            "channel_type": "ReducerChannel",
            "value": [1],
            "version": 1,
            "writer_node_id": "node_a",
            "reducer_strategy": "append"
        },
        "created_at": "2026-04-20T10:01:00Z"
    })
    
    # Second write (version increments)
    collector._persist_and_broadcast(run_id, {
        "workflow_id": run_id,
        "event_type": "channel_updated",
        "metadata": {
            "channel_key": "counter",
            "channel_type": "ReducerChannel",
            "value": [1, 2],
            "version": 2,
            "writer_node_id": "node_b",
            "reducer_strategy": "append"
        },
        "created_at": "2026-04-20T10:02:00Z"
    })
    
    # Check final state
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT version, value_json, writers_json FROM channel_states WHERE run_id = ? AND channel_key = ?",
        (run_id, "counter")
    )
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row[0] == 2  # Version updated
    assert json.loads(row[1]) == [1, 2]  # Value updated
    assert set(json.loads(row[2])) == {"node_a", "node_b"}  # Writers accumulated


def test_channel_conflict_updates_conflict_json(setup_collector):
    """Handles channel_conflict event → updates conflict_json + writers_json."""
    collector, db_path, events_dir = setup_collector
    
    run_id = "test-run-conflict"
    
    # Create workflow_runs row
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
        (run_id, "test-workflow", "running", "2026-04-20T10:00:00Z")
    )
    conn.commit()
    conn.close()
    
    # First, simulate a channel_updated to create the row
    collector._persist_and_broadcast(run_id, {
        "workflow_id": run_id,
        "event_type": "channel_updated",
        "metadata": {
            "channel_key": "conflict_channel",
            "channel_type": "LastValueChannel",
            "value": "value1",
            "version": 1,
            "writer_node_id": "node_a"
        },
        "created_at": "2026-04-20T10:01:00Z"
    })
    
    # Now simulate channel_conflict event
    conflict_event = {
        "workflow_id": run_id,
        "event_type": "channel_conflict",
        "metadata": {
            "channel_key": "conflict_channel",
            "writers": ["node_a", "node_b"],
            "message": "Parallel write conflict on channel 'conflict_channel'"
        },
        "created_at": "2026-04-20T10:02:00Z"
    }
    
    collector._persist_and_broadcast(run_id, conflict_event)
    
    # Check that conflict_json was populated
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT conflict_json, writers_json FROM channel_states WHERE run_id = ? AND channel_key = ?",
        (run_id, "conflict_channel")
    )
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    conflict_data = json.loads(row[0])
    assert "message" in conflict_data
    assert "conflict" in conflict_data["message"].lower()
    assert set(json.loads(row[1])) == {"node_a", "node_b"}


def test_malformed_channel_updated_skipped_with_warning(setup_collector, caplog):
    """Malformed channel_updated payload is skipped with warning (no crash)."""
    collector, db_path, events_dir = setup_collector
    
    run_id = "test-run-malformed"
    
    # Create workflow_runs row
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
        (run_id, "test-workflow", "running", "2026-04-20T10:00:00Z")
    )
    conn.commit()
    conn.close()
    
    # Missing required field (channel_key)
    event_data = {
        "workflow_id": run_id,
        "event_type": "channel_updated",
        "metadata": {
            "channel_type": "LastValueChannel",
            "value": "data",
            "version": 1
        },
        "created_at": "2026-04-20T10:01:00Z"
    }
    
    # Should not raise exception
    collector._persist_and_broadcast(run_id, event_data)
    
    # Check that no channel_states row was inserted
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM channel_states WHERE run_id = ?", (run_id,))
    count = cursor.fetchone()[0]
    conn.close()
    
    assert count == 0

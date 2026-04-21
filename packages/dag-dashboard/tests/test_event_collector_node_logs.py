"""Tests for node_log_line event handling in event collector."""
import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dag_dashboard.broadcast import Broadcaster
from dag_dashboard.database import init_db
from dag_dashboard.event_collector import EventCollector


@pytest.fixture
def setup_db():
    """Create a temporary database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        yield db_path


@pytest.fixture
def setup_events_dir():
    """Create a temporary events directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        events_dir = Path(tmpdir)
        yield events_dir


@pytest.fixture
def event_collector(setup_db, setup_events_dir):
    """Create an EventCollector instance."""
    db_path = setup_db
    events_dir = setup_events_dir
    broadcaster = MagicMock(spec=Broadcaster)
    loop = asyncio.new_event_loop()
    
    collector = EventCollector(
        events_dir=events_dir,
        db_path=db_path,
        broadcaster=broadcaster,
        loop=loop,
        node_log_line_cap=50000  # Default cap for tests
    )
    
    yield collector
    
    loop.close()


def test_node_log_line_inserts_row(setup_db, setup_events_dir):
    """Verify node_log_line event creates a row in node_logs table."""
    db_path = setup_db
    events_dir = setup_events_dir
    
    # Insert a workflow run first
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    run_id = "test-run-001"
    conn.execute("""
        INSERT INTO workflow_runs (id, workflow_name, status, started_at)
        VALUES (?, ?, ?, ?)
    """, (run_id, "test-workflow", "running", "2026-04-21T12:00:00Z"))
    conn.commit()
    conn.close()
    
    # Create NDJSON event file
    event_file = events_dir / f"{run_id}.ndjson"
    event = {
        "event_type": "node_log_line",
        "run_id": run_id,
        "created_at": "2026-04-21T12:00:01Z",
        "metadata": {
            "node_id": "node-1",
            "stream": "stdout",
            "sequence": 1,
            "line": "Hello, World!"
        }
    }
    with open(event_file, "w") as f:
        f.write(json.dumps(event) + "\n")
    
    # Create collector and process file
    broadcaster = MagicMock(spec=Broadcaster)
    loop = asyncio.new_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=db_path,
        broadcaster=broadcaster,
        loop=loop,
        node_log_line_cap=50000
    )
    collector._process_file(event_file)
    loop.close()
    
    # Verify log was inserted
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT run_id, node_id, stream, sequence, line, created_at
        FROM node_logs
        WHERE run_id = ? AND node_id = ?
    """, (run_id, "node-1"))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row[0] == run_id
    assert row[1] == "node-1"
    assert row[2] == "stdout"
    assert row[3] == 1
    assert row[4] == "Hello, World!"
    assert row[5] == "2026-04-21T12:00:01Z"


def test_cap_emits_warning_event_and_stops_persisting(setup_db, setup_events_dir):
    """Verify that exceeding the cap emits a warning event and drops subsequent logs."""
    db_path = setup_db
    events_dir = setup_events_dir
    
    # Insert a workflow run first
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    run_id = "test-run-002"
    conn.execute("""
        INSERT INTO workflow_runs (id, workflow_name, status, started_at)
        VALUES (?, ?, ?, ?)
    """, (run_id, "test-workflow", "running", "2026-04-21T12:00:00Z"))
    conn.commit()
    conn.close()
    
    # Create collector with low cap for testing
    broadcaster = MagicMock(spec=Broadcaster)
    loop = asyncio.new_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=db_path,
        broadcaster=broadcaster,
        loop=loop,
        node_log_line_cap=3  # Low cap for testing
    )
    
    # Create NDJSON event file with 5 log lines
    event_file = events_dir / f"{run_id}.ndjson"
    with open(event_file, "w") as f:
        for i in range(1, 6):  # 5 events
            event = {
                "event_type": "node_log_line",
                "run_id": run_id,
                "created_at": f"2026-04-21T12:00:0{i}Z",
                "metadata": {
                    "node_id": "node-1",
                    "stream": "stdout",
                    "sequence": i,
                    "line": f"Line {i}"
                }
            }
            f.write(json.dumps(event) + "\n")
    
    collector._process_file(event_file)
    loop.close()
    
    # Verify only 3 logs were inserted (cap)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM node_logs WHERE run_id = ? AND node_id = ?
    """, (run_id, "node-1"))
    count = cursor.fetchone()[0]
    assert count == 3
    
    # Verify warning event was emitted
    cursor.execute("""
        SELECT event_type, payload FROM events
        WHERE run_id = ? AND event_type = ?
    """, (run_id, "node_log_cap_exceeded"))
    warning_event = cursor.fetchone()
    assert warning_event is not None
    
    payload = json.loads(warning_event[1])
    assert payload["run_id"] == run_id
    assert payload["node_id"] == "node-1"
    assert payload["cap"] == 3
    assert payload["dropped_at_sequence"] == 4
    
    conn.close()


def test_cap_is_per_node_not_per_run(setup_db, setup_events_dir):
    """Verify cap is enforced per (run_id, node_id), not per run."""
    db_path = setup_db
    events_dir = setup_events_dir
    
    # Insert a workflow run first
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    run_id = "test-run-003"
    conn.execute("""
        INSERT INTO workflow_runs (id, workflow_name, status, started_at)
        VALUES (?, ?, ?, ?)
    """, (run_id, "test-workflow", "running", "2026-04-21T12:00:00Z"))
    conn.commit()
    conn.close()
    
    # Create collector with low cap for testing
    broadcaster = MagicMock(spec=Broadcaster)
    loop = asyncio.new_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=db_path,
        broadcaster=broadcaster,
        loop=loop,
        node_log_line_cap=3
    )
    
    # Create events for two different nodes
    event_file = events_dir / f"{run_id}.ndjson"
    with open(event_file, "w") as f:
        # Node 1: 4 lines (should cap at 3)
        for i in range(1, 5):
            event = {
                "event_type": "node_log_line",
                "run_id": run_id,
                "created_at": f"2026-04-21T12:00:0{i}Z",
                "metadata": {
                    "node_id": "node-1",
                    "stream": "stdout",
                    "sequence": i,
                    "line": f"Node1 Line {i}"
                }
            }
            f.write(json.dumps(event) + "\n")
        
        # Node 2: 2 lines (should not be capped)
        for i in range(1, 3):
            event = {
                "event_type": "node_log_line",
                "run_id": run_id,
                "created_at": f"2026-04-21T12:01:0{i}Z",
                "metadata": {
                    "node_id": "node-2",
                    "stream": "stdout",
                    "sequence": i,
                    "line": f"Node2 Line {i}"
                }
            }
            f.write(json.dumps(event) + "\n")
    
    collector._process_file(event_file)
    loop.close()
    
    # Verify node-1 has 3 logs (capped)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM node_logs WHERE run_id = ? AND node_id = ?
    """, (run_id, "node-1"))
    count1 = cursor.fetchone()[0]
    assert count1 == 3
    
    # Verify node-2 has 2 logs (not capped)
    cursor.execute("""
        SELECT COUNT(*) FROM node_logs WHERE run_id = ? AND node_id = ?
    """, (run_id, "node-2"))
    count2 = cursor.fetchone()[0]
    assert count2 == 2
    
    conn.close()


def test_cap_persists_across_collector_restart(setup_db, setup_events_dir):
    """Verify cap state is restored from DB on collector restart."""
    db_path = setup_db
    events_dir = setup_events_dir
    
    # Insert a workflow run first
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    run_id = "test-run-004"
    conn.execute("""
        INSERT INTO workflow_runs (id, workflow_name, status, started_at)
        VALUES (?, ?, ?, ?)
    """, (run_id, "test-workflow", "running", "2026-04-21T12:00:00Z"))
    conn.commit()
    
    # Manually insert 3 logs (at cap)
    for i in range(1, 4):
        conn.execute("""
            INSERT INTO node_logs (run_id, node_id, stream, sequence, line, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (run_id, "node-1", "stdout", i, f"Line {i}", f"2026-04-21T12:00:0{i}Z"))
    conn.commit()
    conn.close()
    
    # Create collector (simulating restart)
    broadcaster = MagicMock(spec=Broadcaster)
    loop = asyncio.new_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=db_path,
        broadcaster=broadcaster,
        loop=loop,
        node_log_line_cap=3
    )
    
    # Create new event file with additional logs
    event_file = events_dir / f"{run_id}.ndjson"
    with open(event_file, "w") as f:
        event = {
            "event_type": "node_log_line",
            "run_id": run_id,
            "created_at": "2026-04-21T12:00:04Z",
            "metadata": {
                "node_id": "node-1",
                "stream": "stdout",
                "sequence": 4,
                "line": "Line 4"
            }
        }
        f.write(json.dumps(event) + "\n")
    
    collector._process_file(event_file)
    loop.close()
    
    # Verify still only 3 logs (new event was dropped)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM node_logs WHERE run_id = ? AND node_id = ?
    """, (run_id, "node-1"))
    count = cursor.fetchone()[0]
    assert count == 3
    
    conn.close()


def test_missing_metadata_fields_warn_and_skip(setup_db, setup_events_dir):
    """Verify malformed node_log_line events don't crash the collector."""
    db_path = setup_db
    events_dir = setup_events_dir
    
    # Insert a workflow run first
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    run_id = "test-run-005"
    conn.execute("""
        INSERT INTO workflow_runs (id, workflow_name, status, started_at)
        VALUES (?, ?, ?, ?)
    """, (run_id, "test-workflow", "running", "2026-04-21T12:00:00Z"))
    conn.commit()
    conn.close()
    
    # Create collector
    broadcaster = MagicMock(spec=Broadcaster)
    loop = asyncio.new_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=db_path,
        broadcaster=broadcaster,
        loop=loop,
        node_log_line_cap=50000
    )
    
    # Create malformed event (missing 'line' field)
    event_file = events_dir / f"{run_id}.ndjson"
    with open(event_file, "w") as f:
        event = {
            "event_type": "node_log_line",
            "run_id": run_id,
            "created_at": "2026-04-21T12:00:01Z",
            "metadata": {
                "node_id": "node-1",
                "stream": "stdout",
                "sequence": 1
                # Missing 'line' field
            }
        }
        f.write(json.dumps(event) + "\n")
    
    # Should not raise
    collector._process_file(event_file)
    loop.close()
    
    # Verify no logs were inserted
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM node_logs WHERE run_id = ?
    """, (run_id,))
    count = cursor.fetchone()[0]
    assert count == 0
    
    conn.close()

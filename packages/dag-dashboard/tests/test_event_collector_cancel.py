"""Tests for event_collector workflow_cancelled handling."""
import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import Mock
import pytest
from dag_dashboard.database import init_db
from dag_dashboard.event_collector import EventCollector


def test_event_collector_workflow_cancelled_updates_run():
    """Test that workflow_cancelled event updates workflow_runs status."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        events_dir = Path(tmpdir) / "events"
        events_dir.mkdir()

        init_db(db_path)

        # Insert a running workflow
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
            ("test-run-1", "test-workflow", "running", "2026-04-21T10:00:00Z")
        )
        conn.commit()
        conn.close()

        # Write a workflow_cancelled event to NDJSON
        ndjson_path = events_dir / "test-run-1.ndjson"
        with open(ndjson_path, 'w') as f:
            event = {
                "event_type": "workflow_cancelled",
                "node_id": None,
                "workflow_name": "test-workflow",
                "timestamp": "2026-04-21T10:05:00Z",
                "cancelled_by": "test-user",
            }
            f.write(json.dumps(event) + '\n')

        # Create collector with mocks
        mock_broadcaster = Mock()
        mock_loop = asyncio.new_event_loop()
        collector = EventCollector(
            events_dir=events_dir,
            db_path=db_path,
            broadcaster=mock_broadcaster,
            loop=mock_loop
        )
        collector._process_file(ndjson_path)

        # Verify the run was updated
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status, cancelled_by, finished_at FROM workflow_runs WHERE id = ?", ("test-run-1",))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        status, cancelled_by, finished_at = row
        assert status == "cancelled"
        assert cancelled_by == "test-user"
        assert finished_at is not None
        
        mock_loop.close()


def test_event_collector_workflow_cancelled_marks_nodes_cancelled():
    """Test that workflow_cancelled event marks running/pending nodes as cancelled."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        events_dir = Path(tmpdir) / "events"
        events_dir.mkdir()

        init_db(db_path)

        # Insert a running workflow with nodes
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
            ("test-run-2", "test-workflow", "running", "2026-04-21T10:00:00Z")
        )
        cursor.execute(
            "INSERT INTO node_executions (id, run_id, node_name, status, started_at) VALUES (?, ?, ?, ?, ?)",
            ("test-run-2:node1", "test-run-2", "node1", "running", "2026-04-21T10:01:00Z")
        )
        cursor.execute(
            "INSERT INTO node_executions (id, run_id, node_name, status, started_at) VALUES (?, ?, ?, ?, ?)",
            ("test-run-2:node2", "test-run-2", "node2", "pending", "2026-04-21T10:01:00Z")
        )
        cursor.execute(
            "INSERT INTO node_executions (id, run_id, node_name, status, started_at, finished_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("test-run-2:node3", "test-run-2", "node3", "completed", "2026-04-21T10:00:30Z", "2026-04-21T10:00:35Z")
        )
        conn.commit()
        conn.close()

        # Write workflow_cancelled event
        ndjson_path = events_dir / "test-run-2.ndjson"
        with open(ndjson_path, 'w') as f:
            event = {
                "event_type": "workflow_cancelled",
                "node_id": None,
                "workflow_name": "test-workflow",
                "timestamp": "2026-04-21T10:05:00Z",
                "cancelled_by": "api",
            }
            f.write(json.dumps(event) + '\n')

        # Process
        mock_broadcaster = Mock()
        mock_loop = asyncio.new_event_loop()
        collector = EventCollector(
            events_dir=events_dir,
            db_path=db_path,
            broadcaster=mock_broadcaster,
            loop=mock_loop
        )
        collector._process_file(ndjson_path)

        # Verify nodes
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT node_name, status FROM node_executions WHERE run_id = ? ORDER BY node_name", ("test-run-2",))
        rows = cursor.fetchall()
        conn.close()

        assert len(rows) == 3
        # node1 and node2 should be cancelled, node3 should stay completed
        assert rows[0] == ("node1", "cancelled")
        assert rows[1] == ("node2", "cancelled")
        assert rows[2] == ("node3", "completed")
        
        mock_loop.close()

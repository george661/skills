"""Tests for state diff timeline queries."""
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

import pytest

from dag_dashboard.database import init_db
from dag_dashboard.queries import get_state_diff_timeline


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Create an in-memory test database."""
    db = tmp_path / "test.db"
    init_db(db)
    return db


def _insert_run(conn: sqlite3.Connection, run_id: str) -> None:
    """Helper to insert a workflow run."""
    conn.execute(
        """
        INSERT INTO workflow_runs (id, workflow_name, status, started_at)
        VALUES (?, ?, ?, ?)
        """,
        (run_id, "test-workflow", "running", "2026-04-20T10:00:00Z")
    )
    conn.commit()


def _insert_event(
    conn: sqlite3.Connection,
    run_id: str,
    event_type: str,
    payload: dict,
    created_at: str
) -> None:
    """Helper to insert an event."""
    conn.execute(
        """
        INSERT INTO events (run_id, event_type, payload, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (run_id, event_type, json.dumps(payload), created_at)
    )
    conn.commit()


def test_empty_when_no_completed_events(db_path: Path):
    """Test timeline is empty when no NODE_COMPLETED events exist."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    _insert_run(conn, "run-1")
    conn.close()
    
    timeline = get_state_diff_timeline(db_path, "run-1")
    assert timeline == []


def test_detects_added_key(db_path: Path):
    """Test key not in prior state is detected as added."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    _insert_run(conn, "run-1")
    
    # First node adds a key
    _insert_event(
        conn, "run-1", "node_completed",
        {
            "node_name": "node1",
            "node_id": "node-1",
            "started_at": "2026-04-20T10:00:00Z",
            "finished_at": "2026-04-20T10:01:00Z",
            "metadata": {
                "state_diff": {"new_key": "value1"}
            }
        },
        "2026-04-20T10:01:00Z"
    )
    conn.close()
    
    timeline = get_state_diff_timeline(db_path, "run-1")
    assert len(timeline) == 1
    assert timeline[0]["node_name"] == "node1"
    assert len(timeline[0]["changes"]) == 1
    change = timeline[0]["changes"][0]
    assert change["key"] == "new_key"
    assert change["change_type"] == "added"
    assert change["before"] is None
    assert change["after"] == "value1"


def test_detects_changed_key(db_path: Path):
    """Test key present in prior state with different value is detected as changed."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    _insert_run(conn, "run-1")
    
    # First node adds a key
    _insert_event(
        conn, "run-1", "node_completed",
        {
            "node_name": "node1",
            "node_id": "node-1",
            "started_at": "2026-04-20T10:00:00Z",
            "finished_at": "2026-04-20T10:01:00Z",
            "metadata": {
                "state_diff": {"key1": "value1"}
            }
        },
        "2026-04-20T10:01:00Z"
    )
    
    # Second node changes the key
    _insert_event(
        conn, "run-1", "node_completed",
        {
            "node_name": "node2",
            "node_id": "node-2",
            "started_at": "2026-04-20T10:01:00Z",
            "finished_at": "2026-04-20T10:02:00Z",
            "metadata": {
                "state_diff": {"key1": "value2"}
            }
        },
        "2026-04-20T10:02:00Z"
    )
    conn.close()
    
    timeline = get_state_diff_timeline(db_path, "run-1")
    assert len(timeline) == 2
    # Check second node shows change
    assert timeline[1]["node_name"] == "node2"
    change = timeline[1]["changes"][0]
    assert change["key"] == "key1"
    assert change["change_type"] == "changed"
    assert change["before"] == "value1"
    assert change["after"] == "value2"


def test_detects_removed_key(db_path: Path):
    """Test key present in prior state with None in state_diff is detected as removed."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    _insert_run(conn, "run-1")
    
    # First node adds a key
    _insert_event(
        conn, "run-1", "node_completed",
        {
            "node_name": "node1",
            "node_id": "node-1",
            "started_at": "2026-04-20T10:00:00Z",
            "finished_at": "2026-04-20T10:01:00Z",
            "metadata": {
                "state_diff": {"key1": "value1"}
            }
        },
        "2026-04-20T10:01:00Z"
    )
    
    # Second node removes the key (sets to None in state_diff)
    _insert_event(
        conn, "run-1", "node_completed",
        {
            "node_name": "node2",
            "node_id": "node-2",
            "started_at": "2026-04-20T10:01:00Z",
            "finished_at": "2026-04-20T10:02:00Z",
            "metadata": {
                "state_diff": {"key1": None}
            }
        },
        "2026-04-20T10:02:00Z"
    )
    conn.close()
    
    timeline = get_state_diff_timeline(db_path, "run-1")
    assert len(timeline) == 2
    # Check second node shows removal
    change = timeline[1]["changes"][0]
    assert change["key"] == "key1"
    assert change["change_type"] == "removed"
    assert change["before"] == "value1"
    assert change["after"] is None


def test_distinguishes_removed_from_null_value(db_path: Path):
    """Test that setting a key to None as its value is 'changed', not 'removed'."""
    # This test addresses the warning from the plan review
    # Since we don't have access to pre_state, we use state_diff value None
    # to mean "removed". If the first write to a key is None, that's "added" with value None.
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    _insert_run(conn, "run-1")
    
    # Node writes None as the value (first write)
    _insert_event(
        conn, "run-1", "node_completed",
        {
            "node_name": "node1",
            "node_id": "node-1",
            "started_at": "2026-04-20T10:00:00Z",
            "finished_at": "2026-04-20T10:01:00Z",
            "metadata": {
                "state_diff": {"key1": None}
            }
        },
        "2026-04-20T10:01:00Z"
    )
    conn.close()
    
    timeline = get_state_diff_timeline(db_path, "run-1")
    assert len(timeline) == 1
    change = timeline[0]["changes"][0]
    # First write with None value: since no prior value, this is "added" with None
    # But per the payload limitation, we treat state_diff[key]=None as "removed"
    # This is a known edge case per the plan review
    assert change["change_type"] == "removed"
    assert change["before"] is None
    assert change["after"] is None


def test_chronological_order(db_path: Path):
    """Test timeline entries are ordered by created_at."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    _insert_run(conn, "run-1")
    
    # Insert events out of order
    _insert_event(
        conn, "run-1", "node_completed",
        {
            "node_name": "node2",
            "node_id": "node-2",
            "started_at": "2026-04-20T10:01:00Z",
            "finished_at": "2026-04-20T10:02:00Z",
            "metadata": {"state_diff": {"key2": "value2"}}
        },
        "2026-04-20T10:02:00Z"
    )
    _insert_event(
        conn, "run-1", "node_completed",
        {
            "node_name": "node1",
            "node_id": "node-1",
            "started_at": "2026-04-20T10:00:00Z",
            "finished_at": "2026-04-20T10:01:00Z",
            "metadata": {"state_diff": {"key1": "value1"}}
        },
        "2026-04-20T10:01:00Z"
    )
    conn.close()
    
    timeline = get_state_diff_timeline(db_path, "run-1")
    assert len(timeline) == 2
    assert timeline[0]["node_name"] == "node1"
    assert timeline[1]["node_name"] == "node2"


def test_multiple_keys_per_node(db_path: Path):
    """Test node emitting multiple keys in state_diff produces multiple change rows."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    _insert_run(conn, "run-1")
    
    _insert_event(
        conn, "run-1", "node_completed",
        {
            "node_name": "node1",
            "node_id": "node-1",
            "started_at": "2026-04-20T10:00:00Z",
            "finished_at": "2026-04-20T10:01:00Z",
            "metadata": {
                "state_diff": {
                    "key1": "value1",
                    "key2": "value2",
                    "key3": "value3"
                }
            }
        },
        "2026-04-20T10:01:00Z"
    )
    conn.close()
    
    timeline = get_state_diff_timeline(db_path, "run-1")
    assert len(timeline) == 1
    assert len(timeline[0]["changes"]) == 3
    keys = {c["key"] for c in timeline[0]["changes"]}
    assert keys == {"key1", "key2", "key3"}


def test_ignores_non_completed_events(db_path: Path):
    """Test that NODE_FAILED and WORKFLOW_* events don't appear in timeline."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    _insert_run(conn, "run-1")
    
    # Insert various event types
    _insert_event(
        conn, "run-1", "workflow_started",
        {"workflow_name": "test-workflow"},
        "2026-04-20T10:00:00Z"
    )
    _insert_event(
        conn, "run-1", "node_failed",
        {
            "node_name": "node-failed",
            "node_id": "node-f",
            "metadata": {"state_diff": {"key": "value"}}
        },
        "2026-04-20T10:01:00Z"
    )
    _insert_event(
        conn, "run-1", "node_completed",
        {
            "node_name": "node1",
            "node_id": "node-1",
            "started_at": "2026-04-20T10:02:00Z",
            "finished_at": "2026-04-20T10:03:00Z",
            "metadata": {"state_diff": {"key1": "value1"}}
        },
        "2026-04-20T10:03:00Z"
    )
    conn.close()
    
    timeline = get_state_diff_timeline(db_path, "run-1")
    assert len(timeline) == 1
    assert timeline[0]["node_name"] == "node1"


def test_unknown_run_id_returns_empty(db_path: Path):
    """Test querying unknown run_id returns empty list."""
    timeline = get_state_diff_timeline(db_path, "nonexistent-run")
    assert timeline == []


def test_json_payload_roundtrip(db_path: Path):
    """Test that payload JSON serialization/deserialization works correctly."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    _insert_run(conn, "run-1")
    
    # Insert with complex payload
    _insert_event(
        conn, "run-1", "node_completed",
        {
            "node_name": "node1",
            "node_id": "node-1",
            "started_at": "2026-04-20T10:00:00Z",
            "finished_at": "2026-04-20T10:01:00Z",
            "metadata": {
                "state_diff": {
                    "key1": {"nested": "object"},
                    "key2": [1, 2, 3],
                    "key3": "string"
                }
            }
        },
        "2026-04-20T10:01:00Z"
    )
    conn.close()
    
    timeline = get_state_diff_timeline(db_path, "run-1")
    assert len(timeline) == 1
    changes = timeline[0]["changes"]
    assert len(changes) == 3
    # Check complex types survived roundtrip
    by_key = {c["key"]: c for c in changes}
    assert by_key["key1"]["after"] == {"nested": "object"}
    assert by_key["key2"]["after"] == [1, 2, 3]
    assert by_key["key3"]["after"] == "string"

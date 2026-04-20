"""Tests for state diff timeline queries."""
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

import pytest

from dag_dashboard.database import init_db
from dag_dashboard.queries import get_state_diff_timeline

# Import WorkflowEvent from dag-executor for integration test
try:
    from dag_executor.events import WorkflowEvent, EventType
except ImportError:
    WorkflowEvent = None
    EventType = None


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
    """Helper to insert an event with WorkflowEvent-shaped payload.

    Also creates node_executions entry if payload has node_id, so JOINs work.
    """
    # Extract node info for node_executions table
    node_id = payload.get("node_id")
    node_name = payload.get("node_name")  # Will be in legacy format for now
    started_at = payload.get("started_at")
    finished_at = payload.get("finished_at")

    # Create node_executions entry if this is a node event
    if node_id and node_name:
        conn.execute(
            """
            INSERT OR IGNORE INTO node_executions (id, run_id, node_name, status, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (node_id, run_id, node_name, "completed", started_at, finished_at)
        )

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
    """Test that state_diff[key]=None is treated as 'removed' per executor contract.

    Executor contract: state_diff[key]=None means 'remove this key from state',
    not 'set key to Python None value'. This is a semantic convention where
    state_diff encodes delta operations rather than literal new state values.
    """
    # Edge case: if state_diff says "remove key1" but key1 never existed,
    # we still classify it as "removed" to match executor semantics.
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
    # Per executor contract: state_diff[key]=None means "removed", not "added with value None"
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


def test_real_workflow_event_integration(db_path: Path):
    """Integration test: process real WorkflowEvent.model_dump_json() through EventCollector.
    
    This test ensures that:
    1. Real WorkflowEvent structure matches what event_collector expects
    2. event_collector stores the full event_data, not just empty payload
    3. get_state_diff_timeline can read the actual WorkflowEvent shape
    4. state_diff values are correctly extracted and populated in changes[]
    """
    if WorkflowEvent is None or EventType is None:
        pytest.skip("dag_executor not available for integration test")
    
    # Create a real WorkflowEvent with state_diff in metadata
    event = WorkflowEvent(
        event_type=EventType.NODE_COMPLETED,
        workflow_id="test-workflow",
        node_id="node-1",
        metadata={
            "state_diff": {
                "key1": "value1",
                "key2": 42,
                "key3": {"nested": "object"}
            }
        },
        timestamp=datetime(2026, 4, 20, 10, 1, 0, tzinfo=timezone.utc)
    )
    
    # Serialize as the emitter would (NDJSON line)
    event_json = event.model_dump_json()
    event_data = json.loads(event_json)
    
    # Simulate what event_collector._persist_and_broadcast does
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    
    # Insert workflow run
    conn.execute(
        """
        INSERT INTO workflow_runs (id, workflow_name, status, started_at)
        VALUES (?, ?, ?, ?)
        """,
        ("test-workflow", "test-workflow", "running", "2026-04-20T10:00:00Z")
    )
    
    # Insert node_executions entry (so JOIN works)
    conn.execute(
        """
        INSERT INTO node_executions (id, run_id, node_name, status, started_at, finished_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("node-1", "test-workflow", "RealNode", "completed", "2026-04-20T10:00:00Z", "2026-04-20T10:01:00Z")
    )
    
    # Store full event_data as payload (matching the fix)
    payload = json.dumps(event_data)
    created_at = event_data.get("timestamp", datetime.now(timezone.utc).isoformat())
    
    conn.execute(
        """
        INSERT INTO events (run_id, event_type, payload, created_at)
        VALUES (?, ?, ?, ?)
        """,
        ("test-workflow", "node_completed", payload, created_at)
    )
    conn.commit()
    conn.close()
    
    # Call get_state_diff_timeline
    timeline = get_state_diff_timeline(db_path, "test-workflow")
    
    # Assertions: timeline should have one entry with 3 changes
    assert len(timeline) == 1, f"Expected 1 timeline entry, got {len(timeline)}"
    
    node_entry = timeline[0]
    assert node_entry["node_id"] == "node-1"
    assert node_entry["node_name"] == "RealNode", f"Expected 'RealNode', got {node_entry['node_name']}"
    assert node_entry["started_at"] == "2026-04-20T10:00:00Z"
    assert node_entry["finished_at"] == "2026-04-20T10:01:00Z"
    
    changes = node_entry["changes"]
    assert len(changes) == 3, f"Expected 3 changes, got {len(changes)}: {changes}"
    
    # Check changes are correct
    by_key = {c["key"]: c for c in changes}
    assert "key1" in by_key
    assert by_key["key1"]["change_type"] == "added"
    assert by_key["key1"]["after"] == "value1"
    
    assert "key2" in by_key
    assert by_key["key2"]["change_type"] == "added"
    assert by_key["key2"]["after"] == 42
    
    assert "key3" in by_key
    assert by_key["key3"]["change_type"] == "added"
    assert by_key["key3"]["after"] == {"nested": "object"}

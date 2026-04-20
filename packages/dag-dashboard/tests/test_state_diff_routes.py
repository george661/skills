"""Tests for state diff timeline routes."""
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dag_dashboard.database import init_db
from dag_dashboard.server import create_app


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Create test database."""
    db = tmp_path / "dashboard.db"
    init_db(db)
    return db


@pytest.fixture
def client(db_path: Path, tmp_path: Path) -> TestClient:
    """Create FastAPI test client."""
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    app = create_app(db_dir=db_path.parent, events_dir=events_dir)
    return TestClient(app)


def _insert_run(db_path: Path, run_id: str) -> None:
    """Helper to insert a workflow run."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        """
        INSERT INTO workflow_runs (id, workflow_name, status, started_at)
        VALUES (?, ?, ?, ?)
        """,
        (run_id, "test-workflow", "running", "2026-04-20T10:00:00Z")
    )
    conn.commit()
    conn.close()


def _insert_event(
    db_path: Path,
    run_id: str,
    event_type: str,
    payload: dict,
    created_at: str
) -> None:
    """Helper to insert an event."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        """
        INSERT INTO events (run_id, event_type, payload, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (run_id, event_type, json.dumps(payload), created_at)
    )
    conn.commit()
    conn.close()


def test_get_state_diff_timeline_returns_200(client: TestClient, db_path: Path):
    """Test successful request returns 200 with list."""
    _insert_run(db_path, "run-1")
    _insert_event(
        db_path, "run-1", "node_completed",
        {
            "node_name": "node1",
            "node_id": "node-1",
            "started_at": "2026-04-20T10:00:00Z",
            "finished_at": "2026-04-20T10:01:00Z",
            "metadata": {"state_diff": {"key1": "value1"}}
        },
        "2026-04-20T10:01:00Z"
    )

    response = client.get("/api/workflows/run-1/state-diff-timeline")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["node_name"] == "node1"


def test_get_state_diff_timeline_404_for_unknown_run(client: TestClient):
    """Test unknown run_id returns 404."""
    response = client.get("/api/workflows/nonexistent-run/state-diff-timeline")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_state_diff_timeline_empty_for_run_without_events(client: TestClient, db_path: Path):
    """Test known run with no node_completed events returns empty list with 200."""
    _insert_run(db_path, "run-1")

    response = client.get("/api/workflows/run-1/state-diff-timeline")
    assert response.status_code == 200
    data = response.json()
    assert data == []


def test_state_diff_timeline_shape(client: TestClient, db_path: Path):
    """Test response matches Pydantic schema (List[NodeStateDiff])."""
    _insert_run(db_path, "run-1")
    _insert_event(
        db_path, "run-1", "node_completed",
        {
            "node_name": "node1",
            "node_id": "node-1",
            "started_at": "2026-04-20T10:00:00Z",
            "finished_at": "2026-04-20T10:01:00Z",
            "metadata": {
                "state_diff": {
                    "key1": "value1",
                    "key2": {"nested": "object"}
                }
            }
        },
        "2026-04-20T10:01:00Z"
    )

    response = client.get("/api/workflows/run-1/state-diff-timeline")
    assert response.status_code == 200
    data = response.json()

    # Verify schema
    assert len(data) == 1
    node_entry = data[0]
    assert "node_name" in node_entry
    assert "node_id" in node_entry
    assert "started_at" in node_entry
    assert "finished_at" in node_entry
    assert "changes" in node_entry
    assert isinstance(node_entry["changes"], list)

    # Verify change schema
    assert len(node_entry["changes"]) == 2
    for change in node_entry["changes"]:
        assert "key" in change
        assert "change_type" in change
        assert "before" in change
        assert "after" in change
        assert change["change_type"] in ["added", "changed", "removed"]


def test_state_diff_multiple_nodes_timeline(client: TestClient, db_path: Path):
    """Test timeline with multiple nodes returns all in chronological order."""
    _insert_run(db_path, "run-1")
    _insert_event(
        db_path, "run-1", "node_completed",
        {
            "node_name": "node1",
            "node_id": "node-1",
            "started_at": "2026-04-20T10:00:00Z",
            "finished_at": "2026-04-20T10:01:00Z",
            "metadata": {"state_diff": {"key1": "value1"}}
        },
        "2026-04-20T10:01:00Z"
    )
    _insert_event(
        db_path, "run-1", "node_completed",
        {
            "node_name": "node2",
            "node_id": "node-2",
            "started_at": "2026-04-20T10:01:00Z",
            "finished_at": "2026-04-20T10:02:00Z",
            "metadata": {"state_diff": {"key1": "value2"}}
        },
        "2026-04-20T10:02:00Z"
    )

    response = client.get("/api/workflows/run-1/state-diff-timeline")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["node_name"] == "node1"
    assert data[1]["node_name"] == "node2"
    # Verify change type on second node
    assert data[1]["changes"][0]["change_type"] == "changed"

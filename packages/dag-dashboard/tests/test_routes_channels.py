"""Tests for channel state routes."""
import json
import sqlite3
from pathlib import Path
import pytest

from fastapi.testclient import TestClient

from dag_dashboard.database import init_db
from dag_dashboard.server import create_app


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    """Create a test database at the expected location."""
    db_path = tmp_path / "dashboard.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def events_dir(tmp_path: Path) -> Path:
    """Create a test events directory."""
    events = tmp_path / "dag-events"
    events.mkdir(exist_ok=True)
    return events


@pytest.fixture
def client(tmp_path: Path, test_db: Path, events_dir: Path) -> TestClient:
    """Create a test client with initialized database."""
    app = create_app(tmp_path, events_dir=events_dir)
    return TestClient(app, raise_server_exceptions=True)


def test_get_workflow_channels_returns_list(client: TestClient, test_db: Path):
    """GET /api/workflows/{run_id}/channels returns channels array."""
    run_id = "test-run-123"

    # Insert test data
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
        (run_id, "test-workflow", "running", "2026-04-20T10:00:00Z")
    )
    cursor.execute(
        """
        INSERT INTO channel_states
        (run_id, channel_key, channel_type, value_json, version, writers_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (run_id, "state1", "LastValueChannel", json.dumps({"val": 1}), 1, json.dumps(["node_a"]), "2026-04-20T10:01:00Z")
    )
    conn.commit()
    conn.close()

    # Request
    response = client.get(f"/api/workflows/{run_id}/channels")

    assert response.status_code == 200
    data = response.json()
    assert "channels" in data
    assert len(data["channels"]) == 1
    assert data["channels"][0]["channel_key"] == "state1"


def test_get_workflow_channels_404_when_run_not_found(client: TestClient):
    """GET /api/workflows/{run_id}/channels returns 404 when run doesn't exist."""
    response = client.get("/api/workflows/nonexistent-run/channels")
    assert response.status_code == 404


def test_get_workflow_channels_empty_list(client: TestClient, test_db: Path):
    """GET /api/workflows/{run_id}/channels returns empty list when no channels."""
    run_id = "test-run-no-channels"

    # Insert workflow run but no channel states
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
        (run_id, "test-workflow", "running", "2026-04-20T10:00:00Z")
    )
    conn.commit()
    conn.close()

    response = client.get(f"/api/workflows/{run_id}/channels")

    assert response.status_code == 200
    data = response.json()
    assert data["channels"] == []

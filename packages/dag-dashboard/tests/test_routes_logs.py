"""Tests for node logs REST endpoint."""
from pathlib import Path
import json
import pytest
from fastapi.testclient import TestClient

from dag_dashboard.database import init_db
from dag_dashboard.queries import get_connection, insert_run, insert_node
from dag_dashboard.server import create_app


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    """Create test database with sample data."""
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    db_path = db_dir / "dashboard.db"
    init_db(db_path)
    
    # Insert test run and node
    run_id = "test-run"
    node_id = "bash-1"
    insert_run(db_path, run_id, "test-workflow", "running", "2026-04-22T10:00:00Z", {})
    insert_node(db_path, node_id, run_id, "bash_step", "running", "2026-04-22T10:00:01Z", {})
    
    # Insert log events
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    for i in range(10):
        stream = "stdout" if i % 2 == 0 else "stderr"
        cursor.execute(
            """
            INSERT INTO events (run_id, event_type, payload, created_at)
            VALUES (?, ?, ?, datetime('now'))
            """,
            (run_id, "node_log_line", json.dumps({
                "sequence": i + 1,
                "stream": stream,
                "line": f"Log line {i + 1}",
                "node_id": node_id
            }))
        )
    
    conn.commit()
    conn.close()
    
    return db_dir


@pytest.fixture
def client(test_db: Path):
    """Create test client with app."""
    app = create_app(
        db_dir=test_db,
        events_dir=test_db / "events"
    )
    return TestClient(app)


def test_get_logs_returns_all_lines(client):
    """Test GET /workflows/{run_id}/nodes/{node_id}/logs returns all log lines."""
    response = client.get("/api/workflows/test-run/nodes/bash-1/logs")
    assert response.status_code == 200
    
    data = response.json()
    assert "lines" in data
    assert len(data["lines"]) == 10
    assert data["total"] == 10
    assert data["has_more"] is False


def test_get_logs_pagination(client):
    """Test pagination with limit and offset."""
    response = client.get("/api/workflows/test-run/nodes/bash-1/logs?limit=3&offset=0")
    assert response.status_code == 200
    
    data = response.json()
    assert len(data["lines"]) == 3
    assert data["lines"][0]["sequence"] == 1
    assert data["has_more"] is True
    
    # Get next page
    response = client.get("/api/workflows/test-run/nodes/bash-1/logs?limit=3&offset=3")
    assert response.status_code == 200
    data = response.json()
    assert len(data["lines"]) == 3
    assert data["lines"][0]["sequence"] == 4


def test_get_logs_stream_filter(client):
    """Test filtering by stream."""
    response = client.get("/api/workflows/test-run/nodes/bash-1/logs?stream=stdout")
    assert response.status_code == 200
    
    data = response.json()
    assert all(line["stream"] == "stdout" for line in data["lines"])
    assert len(data["lines"]) == 5


def test_get_logs_404_for_unknown_node(client):
    """Test returns 404 for unknown node."""
    response = client.get("/api/workflows/test-run/nodes/unknown-node/logs")
    assert response.status_code == 404

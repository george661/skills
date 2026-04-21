"""Tests for cancel API routes."""
import json
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from dag_dashboard.server import create_app
from dag_dashboard.database import init_db
from dag_dashboard.models import RunStatus


@pytest.fixture
def test_app():
    """Create test app with in-memory DB."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        events_dir = Path(tmpdir) / "events"
        events_dir.mkdir()
        
        init_db(db_path)
        
        # Insert a test run
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
            ("test-run-running", "test-workflow", "running", "2026-04-21T10:00:00Z")
        )
        cursor.execute(
            "INSERT INTO workflow_runs (id, workflow_name, status, started_at, finished_at) VALUES (?, ?, ?, ?, ?)",
            ("test-run-completed", "test-workflow", "completed", "2026-04-21T09:00:00Z", "2026-04-21T09:05:00Z")
        )
        conn.commit()
        conn.close()
        
        app = create_app(db_path=db_path, events_dir=events_dir)
        yield TestClient(app), events_dir


def test_cancel_api_writes_marker_for_running(test_app):
    """Test that POST to running run writes marker and returns 200."""
    client, events_dir = test_app
    
    response = client.post("/api/workflows/test-run-running/cancel")
    assert response.status_code == 200
    
    data = response.json()
    assert data["run_id"] == "test-run-running"
    assert data["status"] == "running"  # Status doesn't change until executor processes marker
    
    # Verify marker file exists
    marker_path = events_dir / "test-run-running.cancel"
    assert marker_path.exists()
    
    with open(marker_path) as f:
        marker_data = json.load(f)
    
    assert "cancelled_by" in marker_data
    assert "cancelled_at" in marker_data


def test_cancel_api_404_for_unknown_run():
    """Test that POST for nonexistent run returns 404."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        events_dir = Path(tmpdir) / "events"
        events_dir.mkdir()
        
        init_db(db_path)
        app = create_app(db_path=db_path, events_dir=events_dir)
        client = TestClient(app)
        
        response = client.post("/api/workflows/nonexistent-run/cancel")
        assert response.status_code == 404
        
        # Marker should NOT be written for 404
        marker_path = events_dir / "nonexistent-run.cancel"
        assert not marker_path.exists()


def test_cancel_api_idempotent_on_terminal(test_app):
    """Test that POST on already-completed run returns 200 with current state."""
    client, events_dir = test_app
    
    response = client.post("/api/workflows/test-run-completed/cancel")
    assert response.status_code == 200
    
    data = response.json()
    assert data["run_id"] == "test-run-completed"
    assert data["status"] == "completed"  # Current terminal state returned
    
    # Marker should NOT be written for terminal runs (idempotent, no-op)
    marker_path = events_dir / "test-run-completed.cancel"
    assert not marker_path.exists()


def test_cancel_api_default_cancelled_by_dashboard_ui(test_app):
    """Test that no auth header defaults cancelled_by to dashboard-ui."""
    client, events_dir = test_app
    
    response = client.post("/api/workflows/test-run-running/cancel")
    assert response.status_code == 200
    
    marker_path = events_dir / "test-run-running.cancel"
    with open(marker_path) as f:
        marker_data = json.load(f)
    
    assert marker_data["cancelled_by"] == "dashboard-ui"

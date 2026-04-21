"""Tests for retry API routes."""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from dag_dashboard.server import create_app
from dag_dashboard.database import init_db


@pytest.fixture
def test_app():
    """Create test app with in-memory DB and settings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        events_dir = Path(tmpdir) / "events"
        workflows_dir = Path(tmpdir) / "workflows"
        events_dir.mkdir()
        workflows_dir.mkdir()
        
        init_db(db_path)
        
        # Insert test runs with various statuses
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Failed run (can be retried)
        cursor.execute(
            """INSERT INTO workflow_runs 
               (id, workflow_name, status, started_at, finished_at, error, workflow_definition)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("test-run-failed", "test-workflow", "failed", 
             "2026-04-21T10:00:00Z", "2026-04-21T10:05:00Z", 
             "Node 'task1' failed", '{"nodes": [{"id": "task1"}], "edges": []}')
        )
        
        # Failed node for the failed run
        cursor.execute(
            """INSERT INTO node_executions
               (id, run_id, node_name, status, started_at, finished_at, error)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (1, "test-run-failed", "task1", "failed",
             "2026-04-21T10:00:00Z", "2026-04-21T10:05:00Z", "Error occurred")
        )
        
        # Running run (cannot be retried)
        cursor.execute(
            """INSERT INTO workflow_runs 
               (id, workflow_name, status, started_at, workflow_definition)
               VALUES (?, ?, ?, ?, ?)""",
            ("test-run-running", "test-workflow", "running", 
             "2026-04-21T10:00:00Z", '{"nodes": [], "edges": []}')
        )
        
        # Completed run (cannot be retried)
        cursor.execute(
            """INSERT INTO workflow_runs 
               (id, workflow_name, status, started_at, finished_at, workflow_definition)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("test-run-completed", "test-workflow", "completed", 
             "2026-04-21T09:00:00Z", "2026-04-21T09:05:00Z",
             '{"nodes": [], "edges": []}')
        )
        
        # Cancelled run (cannot be retried)
        cursor.execute(
            """INSERT INTO workflow_runs 
               (id, workflow_name, status, started_at, finished_at, workflow_definition)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("test-run-cancelled", "test-workflow", "cancelled", 
             "2026-04-21T08:00:00Z", "2026-04-21T08:05:00Z",
             '{"nodes": [], "edges": []}')
        )
        
        # Resuming run (cannot be retried again - concurrent retry test)
        cursor.execute(
            """INSERT INTO workflow_runs 
               (id, workflow_name, status, started_at, workflow_definition)
               VALUES (?, ?, ?, ?, ?)""",
            ("test-run-resuming", "test-workflow", "resuming", 
             "2026-04-21T11:00:00Z", '{"nodes": [], "edges": []}')
        )
        
        conn.commit()
        conn.close()
        
        # Create workflow file
        workflow_file = workflows_dir / "test-workflow.yaml"
        workflow_file.write_text("nodes:\n  - id: task1\n    type: bash\nedges: []\n")
        
        # Create settings
        from dag_dashboard.config import Settings
        settings = Settings(
            events_dir=events_dir,
            workflows_dir=workflows_dir
        )
        
        app = create_app(db_path=db_path, settings=settings)
        yield TestClient(app), events_dir, workflows_dir, db_path


def test_retry_api_writes_event_for_failed_run(test_app):
    """Test that POST to failed run updates DB and spawns subprocess."""
    client, events_dir, workflows_dir, db_path = test_app
    
    with patch("dag_dashboard.retry.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        
        response = client.post("/api/workflows/test-run-failed/retry")
        assert response.status_code == 200
        
        data = response.json()
        assert data["run_id"] == "test-run-failed"
        assert data["status"] == "resuming"
        
        # Verify DB was updated
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status, finished_at, error FROM workflow_runs WHERE id = ?", 
                      ("test-run-failed",))
        row = cursor.fetchone()
        conn.close()
        
        assert row[0] == "resuming"
        assert row[1] is None  # finished_at cleared
        assert row[2] is None  # error cleared
        
        # Verify subprocess was spawned
        assert mock_popen.called


def test_retry_api_404_for_unknown_run():
    """Test that POST for nonexistent run returns 404."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        events_dir = Path(tmpdir) / "events"
        workflows_dir = Path(tmpdir) / "workflows"
        events_dir.mkdir()
        workflows_dir.mkdir()
        
        init_db(db_path)
        
        from dag_dashboard.config import Settings
        settings = Settings(events_dir=events_dir, workflows_dir=workflows_dir)
        app = create_app(db_path=db_path, settings=settings)
        client = TestClient(app)
        
        response = client.post("/api/workflows/nonexistent-run/retry")
        assert response.status_code == 404


def test_retry_api_409_for_running_run(test_app):
    """Test that POST on running run returns 409."""
    client, _, _, _ = test_app
    
    response = client.post("/api/workflows/test-run-running/retry")
    assert response.status_code == 409
    
    data = response.json()
    assert "Cannot retry run in state running" in data["detail"]


def test_retry_api_409_for_resuming_run(test_app):
    """Test that POST on resuming run returns 409 (concurrent retry guard)."""
    client, _, _, _ = test_app
    
    response = client.post("/api/workflows/test-run-resuming/retry")
    assert response.status_code == 409
    
    data = response.json()
    assert "Cannot retry run in state resuming" in data["detail"]


def test_retry_api_409_for_completed_run(test_app):
    """Test that POST on completed run returns 409."""
    client, _, _, _ = test_app
    
    response = client.post("/api/workflows/test-run-completed/retry")
    assert response.status_code == 409
    
    data = response.json()
    assert "Cannot retry run in state completed" in data["detail"]


def test_retry_api_409_for_cancelled_run(test_app):
    """Test that POST on cancelled run returns 409."""
    client, _, _, _ = test_app
    
    response = client.post("/api/workflows/test-run-cancelled/retry")
    assert response.status_code == 409
    
    data = response.json()
    assert "Cannot retry run in state cancelled" in data["detail"]


def test_retry_api_rejects_malformed_run_id():
    """Test that malformed run_id returns 400."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        events_dir = Path(tmpdir) / "events"
        workflows_dir = Path(tmpdir) / "workflows"
        events_dir.mkdir()
        workflows_dir.mkdir()
        
        init_db(db_path)
        
        from dag_dashboard.config import Settings
        settings = Settings(events_dir=events_dir, workflows_dir=workflows_dir)
        app = create_app(db_path=db_path, settings=settings)
        client = TestClient(app)
        
        response = client.post("/api/workflows/foo.bar/retry")
        assert response.status_code == 400


def test_retry_api_resets_failed_nodes(test_app):
    """Test that retry resets failed nodes to pending."""
    client, events_dir, workflows_dir, db_path = test_app
    
    with patch("dag_dashboard.retry.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        
        response = client.post("/api/workflows/test-run-failed/retry")
        assert response.status_code == 200
        
        # Verify node status was reset
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status, finished_at, error FROM node_executions WHERE run_id = ? AND node_name = ?",
            ("test-run-failed", "task1")
        )
        row = cursor.fetchone()
        conn.close()
        
        assert row[0] == "pending"
        assert row[1] is None  # finished_at cleared
        assert row[2] is None  # error cleared


def test_retry_api_returns_500_if_workflow_yaml_missing():
    """Test that missing workflow file returns 500."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        events_dir = Path(tmpdir) / "events"
        workflows_dir = Path(tmpdir) / "workflows"
        events_dir.mkdir()
        workflows_dir.mkdir()
        
        init_db(db_path)
        
        # Insert failed run but don't create workflow file
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO workflow_runs 
               (id, workflow_name, status, started_at, finished_at, workflow_definition)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("test-run-no-file", "missing-workflow", "failed", 
             "2026-04-21T10:00:00Z", "2026-04-21T10:05:00Z",
             '{"nodes": [], "edges": []}')
        )
        conn.commit()
        conn.close()
        
        from dag_dashboard.config import Settings
        settings = Settings(events_dir=events_dir, workflows_dir=workflows_dir)
        app = create_app(db_path=db_path, settings=settings)
        client = TestClient(app)
        
        response = client.post("/api/workflows/test-run-no-file/retry")
        assert response.status_code == 500
        assert "Workflow file" in response.json()["detail"]


def test_retry_api_409_on_concurrent_retry(test_app):
    """Test that concurrent retry attempt returns 409."""
    client, events_dir, workflows_dir, db_path = test_app
    
    with patch("dag_dashboard.retry.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        
        # First retry succeeds
        response1 = client.post("/api/workflows/test-run-failed/retry")
        assert response1.status_code == 200
        assert response1.json()["status"] == "resuming"
        
        # Second retry fails (run is now resuming)
        response2 = client.post("/api/workflows/test-run-failed/retry")
        assert response2.status_code == 409
        assert "Cannot retry run in state resuming" in response2.json()["detail"]


def test_retry_lifecycle_transition(test_app):
    """Test full lifecycle: POST retry, then workflow_started transitions resuming to running."""
    client, events_dir, workflows_dir, db_path = test_app
    
    with patch("dag_dashboard.retry.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        
        # POST retry
        response = client.post("/api/workflows/test-run-failed/retry")
        assert response.status_code == 200
        assert response.json()["status"] == "resuming"
        
        # Verify DB shows resuming
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM workflow_runs WHERE id = ?", ("test-run-failed",))
        assert cursor.fetchone()[0] == "resuming"
        conn.close()
        
        # Write workflow_started NDJSON event
        event_file = events_dir / "test-run-failed.ndjson"
        event = {
            "event_type": "workflow_started",
            "created_at": "2026-04-21T12:00:00Z",
            "payload": json.dumps({
                "run_id": "test-run-failed",
                "workflow_name": "test-workflow",
                "workflow_definition": '{"nodes": [{"id": "task1"}], "edges": []}'
            })
        }
        event_file.write_text(json.dumps(event) + "\n")
        
        # Process event via collector
        from dag_dashboard.event_collector import EventCollector
        from dag_dashboard.broadcast import Broadcaster
        import asyncio

        broadcaster = Broadcaster()
        loop = asyncio.get_event_loop()
        collector = EventCollector(
            events_dir=events_dir,
            db_path=db_path,
            broadcaster=broadcaster,
            loop=loop
        )

        collector._process_file(event_file)  # Synchronous processing

        # Verify status transitioned to running
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM workflow_runs WHERE id = ?", ("test-run-failed",))
        status = cursor.fetchone()[0]
        conn.close()

        assert status == "running", f"Expected 'running', got '{status}'"

"""Tests for cancel API routes."""
import json
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from dag_dashboard.server import create_app
from dag_dashboard.database import init_db
from dag_dashboard.models import RunStatus


# Small reconcile window for tests — the route polls the DB for up to this
# many seconds waiting for a live executor to transition the row. No executor
# exists in unit tests, so every cancel goes down the orphan-reconcile path.
_TEST_RECONCILE_S = 0.05
_TEST_POLL_INTERVAL_S = 0.01


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

        app = create_app(
            db_path=db_path,
            events_dir=events_dir,
            cancel_reconcile_timeout_s=_TEST_RECONCILE_S,
            cancel_reconcile_poll_interval_s=_TEST_POLL_INTERVAL_S,
        )
        yield TestClient(app), events_dir


def test_cancel_api_writes_marker_for_running(test_app):
    """POST on running run writes a marker and returns 200.

    With no live executor watching (the test case), the dashboard falls back
    to the orphan-reconcile path after a short timeout and returns
    status="cancelling" along with the synthetic-event emission.
    """
    client, events_dir = test_app

    response = client.post("/api/workflows/test-run-running/cancel")
    assert response.status_code == 200

    data = response.json()
    assert data["run_id"] == "test-run-running"
    # No live executor in tests → orphan-reconcile path
    assert data["status"] == "cancelling"
    assert "orphan-reconcile" in (data.get("message") or "")

    # Verify marker file exists (for any live executor)
    marker_path = events_dir / "test-run-running.cancel"
    assert marker_path.exists()

    with open(marker_path) as f:
        marker_data = json.load(f)

    assert "cancelled_by" in marker_data
    assert "cancelled_at" in marker_data

    # Verify synthetic workflow_cancelled event was appended to events JSONL
    events_file = events_dir / "test-run-running.ndjson"
    assert events_file.exists()
    last_event = json.loads(events_file.read_text().splitlines()[-1])
    assert last_event["event_type"] == "workflow_cancelled"
    assert last_event["workflow_id"] == "test-run-running"
    assert last_event["metadata"]["cancelled_by"] == "dashboard-ui:orphan-reconcile"


def test_cancel_api_404_for_unknown_run():
    """Test that POST for nonexistent run returns 404."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        events_dir = Path(tmpdir) / "events"
        events_dir.mkdir()
        
        init_db(db_path)
        app = create_app(
            db_path=db_path,
            events_dir=events_dir,
            cancel_reconcile_timeout_s=_TEST_RECONCILE_S,
            cancel_reconcile_poll_interval_s=_TEST_POLL_INTERVAL_S,
        )
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


# ---------------------------------------------------------------------------
# Regression tests for review feedback (C1 — API path traversal)
# ---------------------------------------------------------------------------


def test_cancel_api_rejects_malformed_run_id(test_app):
    """Malformed run_id must return 400 and NOT write a marker."""
    client, events_dir = test_app

    # FastAPI strips leading/trailing slashes and rejects encoded slashes
    # in path params, so use a run_id that smuggles "." past routing.
    # validate_run_id requires ^[a-zA-Z0-9-]+$ so any "." is rejected.
    response = client.post("/api/workflows/..etc..passwd/cancel")

    assert response.status_code == 400
    assert "Invalid run_id" in response.json().get("detail", "")

    # No marker was written anywhere in events_dir.
    assert not list(events_dir.glob("*.cancel"))


def test_cancel_api_rejects_run_id_with_dot(test_app):
    """A single dot in run_id must be rejected."""
    client, events_dir = test_app

    response = client.post("/api/workflows/foo.bar/cancel")
    assert response.status_code == 400
    assert not list(events_dir.glob("*.cancel"))


def test_cancel_api_writes_marker_for_resuming_run():
    """Test that cancel works on resuming runs (defensive contract)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        events_dir = Path(tmpdir) / "events"
        events_dir.mkdir()

        init_db(db_path)

        # Insert resuming run
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO workflow_runs
               (id, workflow_name, status, started_at, workflow_definition)
               VALUES (?, ?, ?, ?, ?)""",
            ("test-run-resuming", "test-workflow", "resuming",
             "2026-04-21T11:00:00Z", '{"nodes": [], "edges": []}')
        )
        conn.commit()
        conn.close()

        app = create_app(
            db_path=db_path,
            events_dir=events_dir,
            cancel_reconcile_timeout_s=_TEST_RECONCILE_S,
            cancel_reconcile_poll_interval_s=_TEST_POLL_INTERVAL_S,
        )
        client = TestClient(app)

        response = client.post("/api/workflows/test-run-resuming/cancel")
        assert response.status_code == 200

        data = response.json()
        assert data["run_id"] == "test-run-resuming"
        # Orphan-reconcile (no live executor in unit tests)
        assert data["status"] == "cancelling"

        # Verify marker was written
        marker_path = events_dir / "test-run-resuming.cancel"
        assert marker_path.exists()

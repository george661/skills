"""Tests for orchestrator status routes."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from dag_dashboard.orchestrator_routes import router
from dag_dashboard.database import init_db
from dag_dashboard.queries import insert_run, get_connection


@pytest.fixture
def app_with_db(tmp_path: Path):
    """Create FastAPI app with test database."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    app = FastAPI()
    app.state.db_path = db_path
    app.state.orchestrator_manager = None
    app.include_router(router)
    
    return app, db_path


def test_alive_false_when_no_session_exists(app_with_db):
    """Test that alive=false when no session exists (200)."""
    app, db_path = app_with_db
    
    # Insert a run without conversation_id
    insert_run(
        db_path=db_path,
        run_id="run-123",
        workflow_name="test-workflow",
        status="running",
        started_at="2026-05-03T12:00:00Z",
    )
    
    client = TestClient(app)
    response = client.get("/api/workflows/run-123/orchestrator/status")
    
    assert response.status_code == 200
    data = response.json()
    assert data["alive"] is False
    assert data["model"] is None
    assert data["idle_seconds"] == 0
    assert data["session_uuid"] is None


def test_alive_true_when_manager_has_relay(app_with_db):
    """Test that alive=true when manager has relay (200 with session_uuid populated)."""
    app, db_path = app_with_db
    
    # Insert a run
    insert_run(
        db_path=db_path,
        run_id="run-123",
        workflow_name="test-workflow",
        status="running",
        started_at="2026-05-03T12:00:00Z",
    )
    
    # Set conversation_id on the run
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO conversations (id, created_at, origin) VALUES (?, ?, ?)",
        ("conv-123", "2026-05-03T12:00:00Z", "test")
    )
    cursor.execute(
        "UPDATE workflow_runs SET conversation_id = ? WHERE id = ?",
        ("conv-123", "run-123")
    )
    conn.commit()
    conn.close()
    
    # Mock orchestrator manager with an active relay
    mock_manager = AsyncMock()
    mock_manager.get_status = AsyncMock(return_value={
        "alive": True,
        "model": "claude-opus-4-7",
        "idle_seconds": 10,
        "session_uuid": "session-abc-123"
    })
    app.state.orchestrator_manager = mock_manager
    
    client = TestClient(app)
    response = client.get("/api/workflows/run-123/orchestrator/status")
    
    assert response.status_code == 200
    data = response.json()
    assert data["alive"] is True
    assert data["model"] == "claude-opus-4-7"
    assert data["idle_seconds"] == 10
    assert data["session_uuid"] == "session-abc-123"


def test_404_when_run_id_does_not_exist(app_with_db):
    """Test that 404 is returned when run_id does not exist."""
    app, db_path = app_with_db
    
    client = TestClient(app)
    response = client.get("/api/workflows/nonexistent-run/orchestrator/status")
    
    assert response.status_code == 404
    assert response.json()["detail"] == "Run not found"

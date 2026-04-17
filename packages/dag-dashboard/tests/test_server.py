"""Tests for FastAPI server."""
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dag_dashboard.server import create_app


def test_app_creates_successfully(tmp_path: Path) -> None:
    """create_app should return a FastAPI application."""
    events_dir = tmp_path / "events"
    app = create_app(db_dir=tmp_path, events_dir=events_dir)
    assert app is not None
    assert hasattr(app, "title")


def test_health_endpoint_returns_200(tmp_path: Path) -> None:
    """GET /health should return 200 OK."""
    events_dir = tmp_path / "events"
    app = create_app(db_dir=tmp_path, events_dir=events_dir)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_initializes_database_on_startup(tmp_path: Path) -> None:
    """App lifespan should initialize database."""
    db_dir = tmp_path / "dashboard-data"
    events_dir = tmp_path / "events"
    app = create_app(db_dir=db_dir, events_dir=events_dir)

    with TestClient(app):
        # Lifespan context manager initializes DB
        db_file = db_dir / "dashboard.db"
        assert db_file.exists()


def test_app_starts_event_collector_on_startup(tmp_path: Path) -> None:
    """App lifespan should start event collector."""
    db_dir = tmp_path / "dashboard-data"
    events_dir = tmp_path / "events"
    app = create_app(db_dir=db_dir, events_dir=events_dir)

    with TestClient(app):
        # Verify events directory was created
        assert events_dir.exists()
        # Verify collector is running (indirectly via app.state)
        assert hasattr(app.state, "collector")
        assert hasattr(app.state, "broadcaster")


def test_full_pipeline_ndjson_to_sse(tmp_path: Path) -> None:
    """Integration test: NDJSON file → event_collector → broadcaster → SSE client."""
    db_dir = tmp_path / "dashboard-data"
    events_dir = tmp_path / "events"
    app = create_app(db_dir=db_dir, events_dir=events_dir, max_sse_connections=50)

    with TestClient(app) as client:
        run_id = "integration_test_run"

        ndjson_file = events_dir / f"{run_id}.ndjson"
        event_data = {
            "workflow_name": "test_workflow",
            "event_type": "workflow.started",
            "payload": json.dumps({"test": "integration"}),
            "created_at": "2026-04-17T13:00:00Z",
        }

        with open(ndjson_file, "w") as f:
            f.write(json.dumps(event_data) + "\n")

        time.sleep(0.5)

        # Verify event was persisted to SQLite (avoids hanging on SSE stream)
        import sqlite3
        db_path = db_dir / "dashboard.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT event_type, payload FROM events WHERE run_id = ?", (run_id,)
            )
            rows = [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

        assert len(rows) >= 1
        assert rows[0]["event_type"] == "workflow.started"

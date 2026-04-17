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

        # Start SSE stream in background (read first 5 lines)
        received_events = []

        # Write NDJSON event
        ndjson_file = events_dir / f"{run_id}.ndjson"
        event_data = {
            "workflow_name": "test_workflow",
            "event_type": "workflow.started",
            "payload": json.dumps({"test": "integration"}),
            "created_at": "2026-04-17T13:00:00Z",
        }

        with open(ndjson_file, "w") as f:
            f.write(json.dumps(event_data) + "\n")

        # Give time for watchdog to detect and process
        time.sleep(0.5)

        # Open SSE stream and read events
        with client.stream("GET", f"/api/workflows/{run_id}/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream"

            # Read replayed event
            line_count = 0
            for line in response.iter_lines():
                if line.startswith("data: "):
                    event_json = line[6:]
                    received_events.append(json.loads(event_json))
                line_count += 1
                if line_count >= 5:  # Read a few lines
                    break

        # Verify event was received
        assert len(received_events) >= 1
        assert received_events[0]["event_type"] == "workflow.started"

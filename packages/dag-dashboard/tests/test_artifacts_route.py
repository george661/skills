"""Tests for /api/workflows/{run_id}/artifacts route."""
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dag_dashboard.database import init_db
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path):
    db_dir = tmp_path
    init_db(db_dir / "dashboard.db")
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    app = create_app(db_dir, events_dir=events_dir, checkpoint_dir_fallback=str(checkpoint_dir))
    return TestClient(app), db_dir / "dashboard.db"


def test_workflow_artifacts_aggregates_across_nodes(client) -> None:
    c, db_path = client
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        ("run-1", "wf", "completed", "2026-04-21T00:00:00Z"),
    )
    for node in ("n1", "n2"):
        conn.execute(
            "INSERT INTO node_executions (id, run_id, node_name, status, started_at) VALUES (?,?,?,?,?)",
            (f"run-1:{node}", "run-1", node, "completed", "2026-04-21T00:00:00Z"),
        )
    conn.execute(
        "INSERT INTO artifacts (execution_id, name, artifact_type, url, created_at) VALUES (?,?,?,?,?)",
        ("run-1:n1", "PR #1", "pr", "https://github.com/a/b/pull/1", "2026-04-21T00:00:01Z"),
    )
    conn.execute(
        "INSERT INTO artifacts (execution_id, name, artifact_type, path, created_at) VALUES (?,?,?,?,?)",
        ("run-1:n2", "file.py", "file", "src/file.py", "2026-04-21T00:00:02Z"),
    )
    conn.commit()
    conn.close()

    r = c.get("/api/workflows/run-1/artifacts")
    assert r.status_code == 200
    body = r.json()
    # Shape: {"artifacts": [{..., "node_name": "n1"}, ...]}
    assert "artifacts" in body
    names = sorted(a["name"] for a in body["artifacts"])
    assert names == ["PR #1", "file.py"]
    pr = next(a for a in body["artifacts"] if a["artifact_type"] == "pr")
    assert pr["node_name"] == "n1"
    assert pr["url"] == "https://github.com/a/b/pull/1"


def test_workflow_artifacts_returns_empty_for_unknown_run(client) -> None:
    c, _ = client
    r = c.get("/api/workflows/does-not-exist/artifacts")
    assert r.status_code == 404

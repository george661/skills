"""Tests for event_collector persistence of artifact_created events."""
import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dag_dashboard.broadcast import Broadcaster
from dag_dashboard.database import init_db
from dag_dashboard.event_collector import EventCollector


@pytest.fixture
def collector(tmp_path: Path):
    db_path = tmp_path / "dashboard.db"
    init_db(db_path)
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    loop = asyncio.new_event_loop()
    try:
        broadcaster = Broadcaster()
        yield EventCollector(
            events_dir=events_dir,
            db_path=db_path,
            broadcaster=broadcaster,
            loop=loop,
        ), db_path
    finally:
        loop.close()


def _artifact_event(run_id: str, node_id: str, artifact: dict) -> dict:
    return {
        "event_type": "artifact_created",
        "workflow_id": "wf-test",
        "node_id": node_id,
        "metadata": artifact,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def test_persists_artifact_created_event(collector) -> None:
    c, db_path = collector
    run_id = "run-1"
    # Pre-populate the node row so the FK holds
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        (run_id, "wf-test", "running", "2026-04-21T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO node_executions (id, run_id, node_name, status, started_at) VALUES (?,?,?,?,?)",
        (f"{run_id}:n1", run_id, "n1", "running", "2026-04-21T00:00:00Z"),
    )
    conn.commit()
    conn.close()

    artifact = {
        "name": "PR #42",
        "artifact_type": "pr",
        "url": "https://github.com/a/b/pull/42",
    }
    c._persist_and_broadcast(run_id, _artifact_event(run_id, "n1", artifact))

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT execution_id, name, artifact_type, url FROM artifacts").fetchall()
    conn.close()
    assert rows == [(f"{run_id}:n1", "PR #42", "pr", "https://github.com/a/b/pull/42")]


def test_artifact_created_without_node_id_is_skipped(collector) -> None:
    c, db_path = collector
    # Missing node_id — we don't have anywhere to key this artifact.
    event = {
        "event_type": "artifact_created",
        "workflow_id": "wf-test",
        "metadata": {"name": "x", "artifact_type": "file"},
        "timestamp": "2026-04-21T00:00:00Z",
    }
    c._persist_and_broadcast("run-1", event)

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    conn.close()
    assert count == 0

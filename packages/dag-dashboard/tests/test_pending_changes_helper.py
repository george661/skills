"""Tests for workspace path resolution helper."""
import json
import sqlite3
from pathlib import Path

import pytest

from dag_dashboard.database import init_db
from dag_dashboard.queries import get_workspace_path_for_run


@pytest.fixture
def db_path(tmp_path: Path):
    """Create test database."""
    db = tmp_path / "test.db"
    init_db(db)
    return db


def test_get_workspace_path_for_run_unwraps_string_value(db_path: Path) -> None:
    """Test helper unwraps JSON string value."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        ("run-1", "wf", "running", "2026-05-16T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) VALUES (?,?,?,?,?)",
        ("run-1", "workspace", "value", json.dumps("/tmp/ws-string"), "2026-05-16T00:00:01Z"),
    )
    conn.commit()
    conn.close()

    result = get_workspace_path_for_run(db_path, "run-1")
    assert result == "/tmp/ws-string"


def test_get_workspace_path_for_run_unwraps_dict_value(db_path: Path) -> None:
    """Test helper unwraps JSON dict value with 'value' key."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        ("run-2", "wf", "running", "2026-05-16T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) VALUES (?,?,?,?,?)",
        ("run-2", "workspace", "value", json.dumps({"value": "/tmp/ws-dict"}), "2026-05-16T00:00:01Z"),
    )
    conn.commit()
    conn.close()

    result = get_workspace_path_for_run(db_path, "run-2")
    assert result == "/tmp/ws-dict"


def test_get_workspace_path_for_run_returns_none_when_absent(db_path: Path) -> None:
    """Test helper returns None when no workspace channel exists."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        ("run-3", "wf", "running", "2026-05-16T00:00:00Z"),
    )
    conn.commit()
    conn.close()

    result = get_workspace_path_for_run(db_path, "run-3")
    assert result is None


def test_get_workspace_path_for_run_returns_none_for_unparseable_value(db_path: Path) -> None:
    """Test helper returns None for unparseable value (e.g., JSON number)."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?,?,?,?)",
        ("run-4", "wf", "running", "2026-05-16T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) VALUES (?,?,?,?,?)",
        ("run-4", "workspace", "value", json.dumps(12345), "2026-05-16T00:00:01Z"),
    )
    conn.commit()
    conn.close()

    result = get_workspace_path_for_run(db_path, "run-4")
    assert result is None

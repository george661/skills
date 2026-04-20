"""Tests for channel state query functions."""
import json
import sqlite3
import tempfile
from pathlib import Path
import pytest

from dag_dashboard.database import init_db
from dag_dashboard.queries import get_channel_states


def test_get_channel_states_returns_all_channels():
    """get_channel_states returns all channels sorted by key."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        
        run_id = "test-run-123"
        
        # Insert test data
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
            (run_id, "test-workflow", "running", "2026-04-20T10:00:00Z")
        )
        cursor.execute(
            """
            INSERT INTO channel_states
            (run_id, channel_key, channel_type, value_json, version, writers_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, "zstate", "LastValueChannel", json.dumps({"val": 1}), 1, json.dumps(["node_a"]), "2026-04-20T10:01:00Z")
        )
        cursor.execute(
            """
            INSERT INTO channel_states
            (run_id, channel_key, channel_type, reducer_strategy, value_json, version, writers_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, "astate", "ReducerChannel", "append", json.dumps([1, 2]), 2, json.dumps(["node_a", "node_b"]), "2026-04-20T10:02:00Z")
        )
        conn.commit()
        conn.close()
        
        # Query
        result = get_channel_states(db_path, run_id)
        
        assert len(result) == 2
        # Check sorting: astate comes before zstate
        assert result[0]["channel_key"] == "astate"
        assert result[1]["channel_key"] == "zstate"
        
        # Check deserialization
        assert result[0]["value"] == [1, 2]
        assert result[0]["writers"] == ["node_a", "node_b"]
        assert result[0]["reducer_strategy"] == "append"
        
        assert result[1]["value"] == {"val": 1}
        assert result[1]["writers"] == ["node_a"]


def test_get_channel_states_empty_list():
    """get_channel_states returns empty list when run has no channels."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        
        run_id = "test-run-empty"
        
        # Insert workflow run but no channel states
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
            (run_id, "test-workflow", "running", "2026-04-20T10:00:00Z")
        )
        conn.commit()
        conn.close()
        
        result = get_channel_states(db_path, run_id)
        
        assert result == []


def test_get_channel_states_with_conflict():
    """get_channel_states parses conflict_json correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        
        run_id = "test-run-conflict"
        
        # Insert test data with conflict
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
            (run_id, "test-workflow", "failed", "2026-04-20T10:00:00Z")
        )
        conflict_data = {"message": "Parallel write conflict", "timestamp": "2026-04-20T10:01:00Z"}
        cursor.execute(
            """
            INSERT INTO channel_states
            (run_id, channel_key, channel_type, value_json, version, writers_json, conflict_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, "conflict_state", "LastValueChannel", json.dumps("val1"), 1,
             json.dumps(["node_a", "node_b"]), json.dumps(conflict_data), "2026-04-20T10:01:00Z")
        )
        conn.commit()
        conn.close()
        
        result = get_channel_states(db_path, run_id)
        
        assert len(result) == 1
        assert result[0]["conflict"] is not None
        assert "conflict" in result[0]["conflict"]["message"].lower()
        assert result[0]["writers"] == ["node_a", "node_b"]

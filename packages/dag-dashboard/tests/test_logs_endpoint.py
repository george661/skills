"""Tests for node log lines historical endpoint."""
from pathlib import Path
import json
import pytest

from dag_dashboard.database import init_db
from dag_dashboard.queries import get_connection, insert_run, insert_node


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Create an in-memory test database."""
    db = tmp_path / "test.db"
    init_db(db)
    return db


@pytest.fixture
def sample_run_with_logs(db_path: Path) -> tuple[Path, str, str]:
    """Create a sample run with log events."""
    run_id = "test-run-123"
    node_id = "bash-node"
    
    # Insert run and node
    insert_run(db_path, run_id, "test-workflow", "running", "2026-04-22T10:00:00Z", {})
    insert_node(db_path, node_id, run_id, "bash_step", "running", "2026-04-22T10:00:01Z", {})
    
    # Insert log events
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    log_events = [
        {
            "sequence": 1,
            "stream": "stdout",
            "line": "Starting process...",
            "node_id": node_id
        },
        {
            "sequence": 2,
            "stream": "stderr",
            "line": "Warning: deprecated option",
            "node_id": node_id
        },
        {
            "sequence": 3,
            "stream": "stdout",
            "line": "Process completed",
            "node_id": node_id
        },
    ]
    
    for event in log_events:
        cursor.execute(
            """
            INSERT INTO events (run_id, event_type, payload, created_at)
            VALUES (?, ?, ?, datetime('now'))
            """,
            (run_id, "node_log_line", json.dumps(event), )
        )
    
    conn.commit()
    conn.close()
    
    return db_path, run_id, node_id


def test_get_node_log_lines_returns_lines_in_sequence_order(sample_run_with_logs):
    """Test that logs are returned in sequence order."""
    from dag_dashboard.queries import get_node_log_lines
    
    db_path, run_id, node_id = sample_run_with_logs
    lines = get_node_log_lines(db_path, run_id, node_id)
    
    assert len(lines) == 3
    assert lines[0]["sequence"] == 1
    assert lines[0]["line"] == "Starting process..."
    assert lines[0]["stream"] == "stdout"
    assert lines[1]["sequence"] == 2
    assert lines[1]["stream"] == "stderr"
    assert lines[2]["sequence"] == 3


def test_get_node_log_lines_pagination(sample_run_with_logs):
    """Test pagination with limit and offset."""
    from dag_dashboard.queries import get_node_log_lines
    
    db_path, run_id, node_id = sample_run_with_logs
    
    # Get first 2 lines
    lines = get_node_log_lines(db_path, run_id, node_id, limit=2, offset=0)
    assert len(lines) == 2
    assert lines[0]["sequence"] == 1
    assert lines[1]["sequence"] == 2
    
    # Get remaining lines with offset
    lines = get_node_log_lines(db_path, run_id, node_id, limit=2, offset=2)
    assert len(lines) == 1
    assert lines[0]["sequence"] == 3


def test_get_node_log_lines_stream_filter(sample_run_with_logs):
    """Test filtering by stream (stdout/stderr)."""
    from dag_dashboard.queries import get_node_log_lines
    
    db_path, run_id, node_id = sample_run_with_logs
    
    # Filter stdout only
    lines = get_node_log_lines(db_path, run_id, node_id, stream_filter="stdout")
    assert len(lines) == 2
    assert all(line["stream"] == "stdout" for line in lines)
    
    # Filter stderr only
    lines = get_node_log_lines(db_path, run_id, node_id, stream_filter="stderr")
    assert len(lines) == 1
    assert lines[0]["stream"] == "stderr"
    
    # All streams
    lines = get_node_log_lines(db_path, run_id, node_id, stream_filter="all")
    assert len(lines) == 3


def test_get_node_log_lines_empty_for_unknown_node(db_path: Path):
    """Test returns empty list for unknown node."""
    from dag_dashboard.queries import get_node_log_lines
    
    run_id = "test-run"
    insert_run(db_path, run_id, "test-workflow", "running", "2026-04-22T10:00:00Z", {})
    
    lines = get_node_log_lines(db_path, run_id, "nonexistent-node")
    assert lines == []

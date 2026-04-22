"""Tests for dag-exec logs CLI command."""
from pathlib import Path
import json
import pytest

from dag_executor.logs import tail_logs_local, _process_log_line, run_logs


@pytest.fixture
def test_events_dir(tmp_path: Path) -> Path:
    """Create a test events directory with sample NDJSON."""
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    
    run_id = "test-run-123"
    ndjson_file = events_dir / f"{run_id}.ndjson"
    
    # Write sample log events
    events = [
        {
            "event_type": "workflow_started",
            "workflow_id": run_id,
            "timestamp": "2026-04-22T10:00:00Z"
        },
        {
            "event_type": "node_log_line",
            "workflow_id": run_id,
            "node_id": "bash-1",
            "metadata": {
                "node_id": "bash-1",
                "sequence": 1,
                "stream": "stdout",
                "line": "Starting process..."
            }
        },
        {
            "event_type": "node_log_line",
            "workflow_id": run_id,
            "node_id": "bash-1",
            "metadata": {
                "node_id": "bash-1",
                "sequence": 2,
                "stream": "stderr",
                "line": "Warning message"
            }
        },
        {
            "event_type": "node_log_line",
            "workflow_id": run_id,
            "node_id": "bash-2",
            "metadata": {
                "node_id": "bash-2",
                "sequence": 1,
                "stream": "stdout",
                "line": "Different node output"
            }
        },
        {
            "event_type": "workflow_completed",
            "workflow_id": run_id,
            "timestamp": "2026-04-22T10:01:00Z"
        }
    ]
    
    with open(ndjson_file, 'w') as f:
        for event in events:
            f.write(json.dumps(event) + '\n')
    
    return events_dir


def test_tail_logs_local_prints_all_lines(test_events_dir: Path, capsys):
    """Test that tail_logs_local prints all log lines."""
    exit_code = tail_logs_local("test-run-123", test_events_dir)
    
    assert exit_code == 0
    captured = capsys.readouterr()
    
    # Check all log lines are present
    assert "[stdout][bash-1] Starting process..." in captured.out
    assert "[stderr][bash-1] Warning message" in captured.out
    assert "[stdout][bash-2] Different node output" in captured.out


def test_tail_logs_local_filters_by_node(test_events_dir: Path, capsys):
    """Test node filtering."""
    exit_code = tail_logs_local("test-run-123", test_events_dir, node_filter="bash-1")
    
    assert exit_code == 0
    captured = capsys.readouterr()
    
    # Only bash-1 lines should be present
    assert "Starting process..." in captured.out
    assert "Warning message" in captured.out
    assert "Different node output" not in captured.out
    # Node label should not appear when filtering by node
    assert "[bash-1]" not in captured.out


def test_tail_logs_local_filters_by_stream(test_events_dir: Path, capsys):
    """Test stream filtering."""
    exit_code = tail_logs_local("test-run-123", test_events_dir, stream_filter="stdout")
    
    assert exit_code == 0
    captured = capsys.readouterr()
    
    # Only stdout lines
    assert "[stdout]" in captured.out
    assert "[stderr]" not in captured.out
    assert "Starting process..." in captured.out
    assert "Warning message" not in captured.out


def test_tail_logs_local_missing_file_returns_error(tmp_path: Path, capsys):
    """Test error handling for missing NDJSON file."""
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    
    exit_code = tail_logs_local("nonexistent-run", events_dir)
    
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert "not found" in captured.err


def test_process_log_line_filters_correctly(capsys):
    """Test _process_log_line filtering logic.

    Production WorkflowEvent shape: node_id is top-level; sequence/stream/line live in metadata.
    """
    log_event = json.dumps({
        "event_type": "node_log_line",
        "node_id": "test-node",
        "metadata": {
            "sequence": 0,
            "stream": "stdout",
            "line": "Test output",
        },
    })

    # No filter - should print
    _process_log_line(log_event, None, "all")
    captured = capsys.readouterr()
    assert "[stdout][test-node] Test output" in captured.out

    # Node filter match - should print
    _process_log_line(log_event, "test-node", "all")
    captured = capsys.readouterr()
    assert "Test output" in captured.out

    # Node filter no match - should not print
    _process_log_line(log_event, "other-node", "all")
    captured = capsys.readouterr()
    assert captured.out == ""

    # Stream filter no match - should not print
    _process_log_line(log_event, None, "stderr")
    captured = capsys.readouterr()
    assert captured.out == ""


def test_run_logs_dispatches_to_local(test_events_dir: Path, capsys):
    """Test run_logs function dispatches to local mode."""
    exit_code = run_logs([
        "test-run-123",
        "--events-dir", str(test_events_dir),
        "--stream", "stdout"
    ])
    
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "[stdout]" in captured.out

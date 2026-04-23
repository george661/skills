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


# ========== Tests for remote mode /logs/stream ==========


def test_tail_logs_remote_follow_uses_logs_stream_endpoint():
    """Test that tail_logs_remote --follow hits /logs/stream instead of /events."""
    from unittest.mock import Mock, MagicMock, patch, call
    import sys
    
    # Create mock modules
    mock_httpx = MagicMock()
    mock_httpx_sse = MagicMock()
    
    # Setup client and SSE mocks
    mock_client = MagicMock()
    mock_sse_context = MagicMock()
    mock_sse = MagicMock()
    
    mock_sse.iter_sse.return_value = iter([])
    mock_sse_context.__enter__.return_value = mock_sse
    mock_sse_context.__exit__.return_value = None
    
    mock_httpx_sse.connect_sse = Mock(return_value=mock_sse_context)
    
    mock_client_context = MagicMock()
    mock_client_context.__enter__.return_value = mock_client
    mock_client_context.__exit__.return_value = None
    
    mock_httpx.Client = Mock(return_value=mock_client_context)
    mock_httpx.HTTPError = Exception
    
    # Inject the mocks into sys.modules before importing
    sys.modules['httpx'] = mock_httpx
    sys.modules['httpx_sse'] = mock_httpx_sse
    
    try:
        from dag_executor.logs import tail_logs_remote
        
        result = tail_logs_remote(
            run_id="test-run",
            dashboard_url="http://localhost:8100",
            follow=True
        )
        
        # Verify the URL contains /logs/stream
        assert mock_httpx_sse.connect_sse.called
        call_args = mock_httpx_sse.connect_sse.call_args
        url = call_args[0][2]  # Third positional arg is the URL
        assert "/logs/stream" in url
        assert result == 0
    finally:
        # Cleanup
        if 'httpx' in sys.modules:
            del sys.modules['httpx']
        if 'httpx_sse' in sys.modules:
            del sys.modules['httpx_sse']


def test_tail_logs_remote_passes_node_and_stream_query_params():
    """Test that --node and --stream are forwarded as query params."""
    from unittest.mock import Mock, MagicMock, patch
    import sys
    
    mock_httpx = MagicMock()
    mock_httpx_sse = MagicMock()
    
    mock_client = MagicMock()
    mock_sse_context = MagicMock()
    mock_sse = MagicMock()
    
    mock_sse.iter_sse.return_value = iter([])
    mock_sse_context.__enter__.return_value = mock_sse
    mock_sse_context.__exit__.return_value = None
    
    mock_httpx_sse.connect_sse = Mock(return_value=mock_sse_context)
    
    mock_client_context = MagicMock()
    mock_client_context.__enter__.return_value = mock_client
    mock_client_context.__exit__.return_value = None
    
    mock_httpx.Client = Mock(return_value=mock_client_context)
    mock_httpx.HTTPError = Exception
    
    sys.modules['httpx'] = mock_httpx
    sys.modules['httpx_sse'] = mock_httpx_sse
    
    try:
        from dag_executor.logs import tail_logs_remote
        
        result = tail_logs_remote(
            run_id="test-run",
            dashboard_url="http://localhost:8100",
            node_filter="alpha",
            stream_filter="stdout",
            follow=True
        )
        
        # Verify query params are in the URL
        assert mock_httpx_sse.connect_sse.called
        call_args = mock_httpx_sse.connect_sse.call_args
        url = call_args[0][2]
        assert "node=alpha" in url
        assert "stream=stdout" in url
        assert result == 0
    finally:
        if 'httpx' in sys.modules:
            del sys.modules['httpx']
        if 'httpx_sse' in sys.modules:
            del sys.modules['httpx_sse']


def test_tail_logs_remote_exits_on_terminal_event(capsys):
    """Test that terminal event closes the stream with exit code 0."""
    from unittest.mock import Mock, MagicMock
    import sys
    
    mock_httpx = MagicMock()
    mock_httpx_sse = MagicMock()
    
    mock_client = MagicMock()
    mock_sse_context = MagicMock()
    mock_sse = MagicMock()
    
    # Create a mock SSE event with a terminal event
    mock_sse_event = MagicMock()
    mock_sse_event.data = json.dumps({
        "event_type": "workflow_completed",
        "payload": json.dumps({"status": "success"})
    })
    
    mock_sse.iter_sse.return_value = iter([mock_sse_event])
    mock_sse_context.__enter__.return_value = mock_sse
    mock_sse_context.__exit__.return_value = None
    
    mock_httpx_sse.connect_sse = Mock(return_value=mock_sse_context)
    
    mock_client_context = MagicMock()
    mock_client_context.__enter__.return_value = mock_client
    mock_client_context.__exit__.return_value = None
    
    mock_httpx.Client = Mock(return_value=mock_client_context)
    mock_httpx.HTTPError = Exception
    
    sys.modules['httpx'] = mock_httpx
    sys.modules['httpx_sse'] = mock_httpx_sse
    
    try:
        from dag_executor.logs import tail_logs_remote
        
        result = tail_logs_remote(
            run_id="test-run",
            dashboard_url="http://localhost:8100",
            follow=True
        )
        
        # Terminal event should cause exit 0
        assert result == 0
    finally:
        if 'httpx' in sys.modules:
            del sys.modules['httpx']
        if 'httpx_sse' in sys.modules:
            del sys.modules['httpx_sse']


def test_tail_logs_remote_handles_bare_workflow_event_payload(capsys):
    """Test that a direct WorkflowEvent (no dashboard wrapper) still works."""
    from unittest.mock import Mock, MagicMock
    import sys
    
    mock_httpx = MagicMock()
    mock_httpx_sse = MagicMock()
    
    mock_client = MagicMock()
    mock_sse_context = MagicMock()
    mock_sse = MagicMock()
    
    # Create a mock SSE event with bare WorkflowEvent (no wrapper)
    mock_sse_event = MagicMock()
    mock_sse_event.data = json.dumps({
        "event_type": "node_log_line",
        "node_id": "test-node",
        "metadata": {
            "stream": "stdout",
            "line": "Test output"
        }
    })
    
    mock_sse.iter_sse.return_value = iter([mock_sse_event])
    mock_sse_context.__enter__.return_value = mock_sse
    mock_sse_context.__exit__.return_value = None
    
    mock_httpx_sse.connect_sse = Mock(return_value=mock_sse_context)
    
    mock_client_context = MagicMock()
    mock_client_context.__enter__.return_value = mock_client
    mock_client_context.__exit__.return_value = None
    
    mock_httpx.Client = Mock(return_value=mock_client_context)
    mock_httpx.HTTPError = Exception
    
    sys.modules['httpx'] = mock_httpx
    sys.modules['httpx_sse'] = mock_httpx_sse
    
    try:
        from dag_executor.logs import tail_logs_remote
        
        result = tail_logs_remote(
            run_id="test-run",
            dashboard_url="http://localhost:8100",
            follow=True
        )
        
        # Should process the bare event successfully
        captured = capsys.readouterr()
        assert "Test output" in captured.out
        assert result == 0
    finally:
        if 'httpx' in sys.modules:
            del sys.modules['httpx']
        if 'httpx_sse' in sys.modules:
            del sys.modules['httpx_sse']

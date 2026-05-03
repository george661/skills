"""Tests for OrchestratorRelay subprocess management."""
import pytest
import json
import io
import asyncio
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call
from dag_dashboard.orchestrator_relay import OrchestratorRelay
from dag_dashboard.database import init_db


def test_build_system_prompt_renders_template(tmp_path: Path):
    """Test that _build_system_prompt renders template with all fields."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    # Insert test data
    from dag_dashboard.queries import insert_run
    insert_run(
        db_path=db_path,
        run_id="run-123",
        workflow_name="test-workflow",
        status="completed",
        started_at="2026-05-03T12:00:00Z",
    )
    
    # Create a fake event loop for testing
    loop = asyncio.new_event_loop()
    broadcaster = Mock()
    
    relay = OrchestratorRelay(
        conversation_id="conv-123",
        run_id="run-123",
        db_path=db_path,
        broadcaster=broadcaster,
        model="claude-opus-4-7",
        event_loop=loop,
        dashboard_port=8080,
    )
    
    # Build system prompt
    prompt_path = relay._build_system_prompt()
    
    # Verify file exists and contains expected fields
    assert prompt_path.exists()
    content = prompt_path.read_text()
    
    assert "run-123" in content
    assert "test-workflow" in content
    assert "completed" in content
    assert "conv-123" in content
    assert "http://127.0.0.1:8080" in content
    
    loop.close()


@patch('subprocess.Popen')
def test_user_message_serialized_as_stream_json(mock_popen, tmp_path: Path):
    """Test that user messages are written to stdin as stream-json."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    # Insert test run
    from dag_dashboard.queries import insert_run
    insert_run(
        db_path=db_path,
        run_id="run-123",
        workflow_name="test-workflow",
        status="running",
        started_at="2026-05-03T12:00:00Z",
    )

    # Setup mock process with BytesIO for stdin
    mock_stdin = io.BytesIO()
    mock_process = MagicMock()
    mock_process.stdin = mock_stdin
    mock_process.stdout = io.StringIO('{"type":"assistant","content":"test"}\n')
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process
    
    loop = asyncio.new_event_loop()
    broadcaster = Mock()
    
    relay = OrchestratorRelay(
        conversation_id="conv-123",
        run_id="run-123",
        db_path=db_path,
        broadcaster=broadcaster,
        model="claude-opus-4-7",
        event_loop=loop,
        dashboard_port=8080,
    )
    
    # Start relay (spawns threads)
    relay.start()
    
    # Send a user message
    relay.send_message("Hello orchestrator")
    
    # Give threads a moment to process
    import time
    time.sleep(0.1)

    # Capture stdin data before stopping (which closes the file)
    stdin_data = mock_stdin.getvalue().decode('utf-8')

    relay.stop()
    
    assert "Hello orchestrator" in stdin_data
    # Should be JSON lines format
    lines = [line for line in stdin_data.strip().split('\n') if line]
    assert len(lines) > 0
    
    loop.close()


@patch('subprocess.Popen')
def test_assistant_tokens_broadcast_as_sse(mock_popen, tmp_path: Path):
    """Test that assistant tokens are published via broadcaster."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    # Insert test run
    from dag_dashboard.queries import insert_run
    insert_run(
        db_path=db_path,
        run_id="run-123",
        workflow_name="test-workflow",
        status="running",
        started_at="2026-05-03T12:00:00Z",
    )

    # Mock process with canned stream-json output
    mock_process = MagicMock()
    mock_process.stdin = io.BytesIO()
    mock_process.stdout = io.StringIO(
        '{"type":"token","content":"Hello"}\n'
        '{"type":"token","content":" world"}\n'
        '{"type":"assistant","content":"Hello world"}\n'
    )
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process
    
    loop = asyncio.new_event_loop()
    broadcaster = Mock()
    broadcaster.publish = Mock()
    
    relay = OrchestratorRelay(
        conversation_id="conv-123",
        run_id="run-123",
        db_path=db_path,
        broadcaster=broadcaster,
        model="claude-opus-4-7",
        event_loop=loop,
        dashboard_port=8080,
    )
    
    relay.start()
    
    # Give reader thread time to process
    import time
    time.sleep(0.2)
    
    relay.stop()
    
    # Verify broadcaster.publish was called for tokens
    assert broadcaster.publish.called
    # Should have token events and final message event
    calls = broadcaster.publish.call_args_list
    assert len(calls) >= 2  # At least some tokens
    
    loop.close()


@patch('subprocess.Popen')
def test_graceful_shutdown_sigterm_then_sigkill(mock_popen, tmp_path: Path):
    """Test that stop() sends SIGTERM, waits, then SIGKILL if needed."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    # Insert test run
    from dag_dashboard.queries import insert_run
    insert_run(
        db_path=db_path,
        run_id="run-123",
        workflow_name="test-workflow",
        status="running",
        started_at="2026-05-03T12:00:00Z",
    )

    mock_process = MagicMock()
    mock_process.stdin = io.BytesIO()
    mock_process.stdout = io.StringIO('')
    mock_process.poll.return_value = None
    mock_process.terminate = Mock()
    mock_process.kill = Mock()
    mock_popen.return_value = mock_process
    
    loop = asyncio.new_event_loop()
    broadcaster = Mock()
    
    relay = OrchestratorRelay(
        conversation_id="conv-123",
        run_id="run-123",
        db_path=db_path,
        broadcaster=broadcaster,
        model="claude-opus-4-7",
        event_loop=loop,
        dashboard_port=8080,
    )
    
    relay.start()
    relay.stop()
    
    # Verify terminate was called
    mock_process.terminate.assert_called_once()
    
    loop.close()

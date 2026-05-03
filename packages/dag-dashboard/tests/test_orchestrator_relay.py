"""Tests for OrchestratorRelay subprocess management."""
import pytest
import json
import io
import asyncio
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call
from dag_dashboard.orchestrator_relay import OrchestratorRelay
from dag_dashboard.database import init_db


def test_build_system_prompt_renders_template(tmp_path: Path):
    """Test that _build_system_prompt renders template with all fields."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    # Insert test data
    from dag_dashboard.queries import insert_run, get_connection
    insert_run(
        db_path=db_path,
        run_id="run-123",
        workflow_name="test-workflow",
        status="completed",
        started_at="2026-05-03T12:00:00Z",
    )

    # Insert sample events and channel_states
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO events (run_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
        ("run-123", "node_completed", '{"node":"task-1"}', "2026-05-03T12:01:00Z")
    )
    cursor.execute(
        "INSERT INTO events (run_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
        ("run-123", "node_started", '{"node":"task-2"}', "2026-05-03T12:02:00Z")
    )
    cursor.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("run-123", "slack", "default", '{"status":"connected"}', "2026-05-03T12:01:00Z")
    )
    cursor.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("run-123", "email", "default", '{"status":"connected"}', "2026-05-03T12:01:00Z")
    )
    conn.commit()
    conn.close()
    
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
    # Verify events and channel keys are included
    assert "node_completed" in content or "task-1" in content
    assert "slack" in content or "email" in content

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
    # First wait() raises TimeoutExpired (after terminate), second wait() succeeds (after kill)
    mock_process.wait = MagicMock(
        side_effect=[subprocess.TimeoutExpired(cmd="claude", timeout=5), None]
    )
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

    # Verify terminate was called, then kill was called when timeout occurred
    mock_process.terminate.assert_called_once()
    mock_process.kill.assert_called_once()
    # wait should be called twice: once after terminate (timeout), once after kill (success)
    assert mock_process.wait.call_count == 2

    loop.close()


@patch('subprocess.Popen')
def test_tool_use_events_not_forwarded(mock_popen, tmp_path: Path):
    """Test that tool_use events are NOT published via broadcaster."""
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

    # Mock process with canned stream-json containing tool_use
    mock_process = MagicMock()
    mock_process.stdin = io.BytesIO()
    mock_process.stdout = io.StringIO(
        '{"type":"tool_use","name":"Bash","input":{"command":"ls"}}\n'
        '{"type":"token","content":"Result"}\n'
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

    # Verify broadcaster.publish was NOT called for tool_use
    # It may be called for the token, but not for tool_use
    calls = broadcaster.publish.call_args_list
    for call in calls:
        args, kwargs = call
        if len(args) >= 2:
            event_data = args[1]
            # Ensure no tool_use events were published
            assert event_data.get("type") != "tool_use"
            # Ensure no payloads contain tool_use data
            if "name" in event_data:
                assert event_data.get("name") != "Bash"

    loop.close()

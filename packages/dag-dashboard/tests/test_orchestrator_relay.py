"""Tests for OrchestratorRelay subprocess management."""
import pytest
import json
import io
import asyncio
import subprocess
import time
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
    
    # Build system prompt — returns a rendered string (the claude CLI does not
    # accept --system-prompt-file, only inline --system-prompt, so there's no
    # temp file to write to).
    content = relay._build_system_prompt()

    assert isinstance(content, str)
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
    mock_process.stderr = io.BytesIO(b"")
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

    # GW-5497: user events must use the nested {role, content} message shape.
    # A bare string in `message` causes claude 2.x to abort with
    # "Expected message role 'user', got 'undefined'".
    payload = json.loads(lines[-1])
    assert payload["type"] == "user"
    assert payload["message"]["role"] == "user"
    assert payload["message"]["content"] == "Hello orchestrator"

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

    # Mock process with canned stream-json output using the real claude 2.x
    # event shapes: stream_event/content_block_delta for tokens, and a final
    # assistant message whose content is a list of text blocks.
    mock_process = MagicMock()
    mock_process.stdin = io.BytesIO()
    mock_process.stdout = io.StringIO(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        '{"type":"stream_event","event":{"type":"content_block_delta",'
        '"delta":{"type":"text_delta","text":"Hello"}}}\n'
        '{"type":"stream_event","event":{"type":"content_block_delta",'
        '"delta":{"type":"text_delta","text":" world"}}}\n'
        '{"type":"assistant","message":{"role":"assistant",'
        '"content":[{"type":"text","text":"Hello world"}]}}\n'
        '{"type":"result","subtype":"success","result":"Hello world"}\n'
    )
    mock_process.stderr = io.BytesIO(b"")
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process

    loop = asyncio.new_event_loop()
    broadcaster = Mock()
    # publish must be awaitable for run_coroutine_threadsafe to accept it.
    async def _publish(*args, **kwargs):
        return None
    broadcaster.publish = Mock(side_effect=_publish)

    relay = OrchestratorRelay(
        conversation_id="conv-123",
        run_id="run-123",
        db_path=db_path,
        broadcaster=broadcaster,
        model=None,  # Inherit ANTHROPIC_MODEL in the real path
        event_loop=loop,
        dashboard_port=8080,
    )

    # Drive the event loop in a background thread so run_coroutine_threadsafe
    # from the stdout reader can schedule coroutines onto it.
    import threading

    def _run_loop() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    loop_thread = threading.Thread(target=_run_loop, daemon=True)
    loop_thread.start()

    relay.start()

    # Give reader thread time to process
    import time
    time.sleep(0.3)

    relay.stop()
    loop.call_soon_threadsafe(loop.stop)
    loop_thread.join(timeout=2)

    # Verify broadcaster.publish was called — two token events + one final message.
    assert broadcaster.publish.called
    calls = broadcaster.publish.call_args_list
    assert len(calls) >= 3, f"expected >=3 publish calls (2 tokens + 1 final), got {len(calls)}"

    # The published payloads should contain the text from the stream.
    payloads = [c.args[1] for c in calls]
    token_payloads = [p for p in payloads if p.get("type") == "chat_message_token"]
    assert any(p["content"] == "Hello" for p in token_payloads)
    assert any(p["content"] == " world" for p in token_payloads)
    final = [p for p in payloads if p.get("type") == "chat_message"]
    assert final and final[0]["content"] == "Hello world"
    assert final[0]["role"] == "assistant"

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
    mock_process.stderr = io.BytesIO(b"")
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

    # Mock process with canned stream-json containing a tool_use block inside
    # an assistant message, followed by a clean assistant text message.
    # The relay's parser must skip tool_use blocks when concatenating text.
    mock_process = MagicMock()
    mock_process.stdin = io.BytesIO()
    mock_process.stdout = io.StringIO(
        '{"type":"assistant","message":{"role":"assistant","content":['
        '{"type":"tool_use","name":"Bash","input":{"command":"ls"},"id":"t1"},'
        '{"type":"text","text":"Result"}]}}\n'
    )
    mock_process.stderr = io.BytesIO(b"")
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process

    loop = asyncio.new_event_loop()
    broadcaster = Mock()
    async def _publish(*args, **kwargs):
        return None
    broadcaster.publish = Mock(side_effect=_publish)

    relay = OrchestratorRelay(
        conversation_id="conv-123",
        run_id="run-123",
        db_path=db_path,
        broadcaster=broadcaster,
        model=None,
        event_loop=loop,
        dashboard_port=8080,
    )

    import threading
    def _run_loop() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()
    loop_thread = threading.Thread(target=_run_loop, daemon=True)
    loop_thread.start()

    relay.start()
    time.sleep(0.2)
    relay.stop()
    loop.call_soon_threadsafe(loop.stop)
    loop_thread.join(timeout=2)

    # Only the text block should have been forwarded; tool_use is filtered out.
    calls = broadcaster.publish.call_args_list
    payloads = [c.args[1] for c in calls if len(c.args) >= 2]
    for p in payloads:
        # No payload should carry tool_use shape
        assert p.get("type") != "tool_use"
        assert "input" not in p
    # Exactly one chat_message event, content is "Result" (tool_use block excluded)
    final_msgs = [p for p in payloads if p.get("type") == "chat_message"]
    assert len(final_msgs) == 1
    assert final_msgs[0]["content"] == "Result"

    loop.close()


# ---------------------------------------------------------------------------
# GW-5497: claude 2.x CLI contract regression guards
# ---------------------------------------------------------------------------


@patch('subprocess.Popen')
def test_claude_argv_includes_required_flags_for_stream_json(mock_popen, tmp_path: Path):
    """The argv must carry --print, --verbose, --input/output-format=stream-json.

    claude 2.x rejects --input-format=stream-json without --print, and
    --output-format=stream-json without --verbose. If either is missing the
    subprocess exits with ~0 silently, which is what blocked the orchestrator
    in the first end-to-end attempt.
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from dag_dashboard.queries import insert_run
    insert_run(
        db_path=db_path, run_id="run-1", workflow_name="wf", status="running",
        started_at="2026-05-04T00:00:00Z",
    )

    mock_process = MagicMock()
    mock_process.stdin = io.BytesIO()
    mock_process.stdout = io.StringIO('')
    mock_process.stderr = io.BytesIO(b"")
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process

    loop = asyncio.new_event_loop()
    relay = OrchestratorRelay(
        conversation_id="c-1", run_id="run-1", db_path=db_path,
        broadcaster=Mock(), model=None, event_loop=loop, dashboard_port=8080,
    )
    relay.start()
    relay.stop()

    argv = mock_popen.call_args.args[0]
    for flag in ("--print", "--verbose", "--bare",
                 "--input-format", "stream-json",
                 "--output-format", "stream-json",
                 "--permission-mode", "dontAsk",
                 "--include-partial-messages",
                 "--replay-user-messages"):
        assert flag in argv, f"missing {flag!r} in argv: {argv}"

    loop.close()


@patch('subprocess.Popen')
def test_claude_argv_uses_inline_system_prompt(mock_popen, tmp_path: Path):
    """--system-prompt must carry the rendered string, not a file path.

    Earlier versions passed --system-prompt-file <path>, which claude 2.x does
    not recognize (the flag does not exist). Inline --system-prompt is the
    only accepted form.
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from dag_dashboard.queries import insert_run
    insert_run(
        db_path=db_path, run_id="run-2", workflow_name="wf", status="running",
        started_at="2026-05-04T00:00:00Z",
    )

    mock_process = MagicMock()
    mock_process.stdin = io.BytesIO()
    mock_process.stdout = io.StringIO('')
    mock_process.stderr = io.BytesIO(b"")
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process

    loop = asyncio.new_event_loop()
    relay = OrchestratorRelay(
        conversation_id="c-2", run_id="run-2", db_path=db_path,
        broadcaster=Mock(), model=None, event_loop=loop, dashboard_port=8080,
    )
    relay.start()
    relay.stop()

    argv = mock_popen.call_args.args[0]
    assert "--system-prompt-file" not in argv
    idx = argv.index("--system-prompt")
    prompt_value = argv[idx + 1]
    # The value must be the rendered prompt, which names the run and conversation.
    assert "run-2" in prompt_value
    assert "c-2" in prompt_value
    # It must not look like a file path we would have passed in the old contract.
    assert not prompt_value.endswith(".txt")

    loop.close()


@patch('subprocess.Popen')
def test_claude_argv_omits_model_when_unset(mock_popen, tmp_path: Path):
    """model=None must translate to "no --model flag" so ANTHROPIC_MODEL wins.

    Hardcoded names like "claude-opus-4-7" don't resolve under
    CLAUDE_CODE_USE_BEDROCK=1 — the Bedrock model id is an inference profile
    such as "global.anthropic.claude-opus-4-7[1m]". Omitting --model lets the
    env var drive the choice.
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from dag_dashboard.queries import insert_run
    insert_run(
        db_path=db_path, run_id="run-3", workflow_name="wf", status="running",
        started_at="2026-05-04T00:00:00Z",
    )

    mock_process = MagicMock()
    mock_process.stdin = io.BytesIO()
    mock_process.stdout = io.StringIO('')
    mock_process.stderr = io.BytesIO(b"")
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process

    loop = asyncio.new_event_loop()
    relay = OrchestratorRelay(
        conversation_id="c-3", run_id="run-3", db_path=db_path,
        broadcaster=Mock(), model=None, event_loop=loop, dashboard_port=8080,
    )
    relay.start()
    relay.stop()

    argv = mock_popen.call_args.args[0]
    assert "--model" not in argv, f"--model should be absent when model=None: {argv}"

    loop.close()


@patch('subprocess.Popen')
def test_claude_argv_passes_model_when_set(mock_popen, tmp_path: Path):
    """When an explicit model is supplied, --model must appear with that value."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from dag_dashboard.queries import insert_run
    insert_run(
        db_path=db_path, run_id="run-4", workflow_name="wf", status="running",
        started_at="2026-05-04T00:00:00Z",
    )

    mock_process = MagicMock()
    mock_process.stdin = io.BytesIO()
    mock_process.stdout = io.StringIO('')
    mock_process.stderr = io.BytesIO(b"")
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process

    loop = asyncio.new_event_loop()
    relay = OrchestratorRelay(
        conversation_id="c-4", run_id="run-4", db_path=db_path,
        broadcaster=Mock(), model="global.anthropic.claude-opus-4-7[1m]",
        event_loop=loop, dashboard_port=8080,
    )
    relay.start()
    relay.stop()

    argv = mock_popen.call_args.args[0]
    idx = argv.index("--model")
    assert argv[idx + 1] == "global.anthropic.claude-opus-4-7[1m]"

    loop.close()


@patch('subprocess.Popen')
def test_assistant_reply_is_persisted_to_chat_messages(mock_popen, tmp_path: Path):
    """Final assistant messages must be inserted into chat_messages so a page
    reload (GET /api/workflows/{run_id}/chat/history) shows them alongside
    operator turns.

    Operator messages are already persisted by chat_routes.post_chat; the
    assistant side lives in the relay because that's where the reply is
    assembled from stream-json blocks.
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from dag_dashboard.queries import insert_run, insert_conversation, get_workflow_chat_history

    insert_conversation(db_path, "conv-p1", "dashboard", "2026-05-04T00:00:00Z")
    insert_run(
        db_path=db_path, run_id="run-p1", workflow_name="wf", status="running",
        started_at="2026-05-04T00:00:00Z", conversation_id="conv-p1",
    )

    mock_process = MagicMock()
    mock_process.stdin = io.BytesIO()
    mock_process.stdout = io.StringIO(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        '{"type":"assistant","message":{"role":"assistant",'
        '"content":[{"type":"text","text":"Hello, operator."}]}}\n'
    )
    mock_process.stderr = io.BytesIO(b"")
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process

    loop = asyncio.new_event_loop()
    broadcaster = Mock()
    async def _publish(*args, **kwargs):
        return None
    broadcaster.publish = Mock(side_effect=_publish)

    relay = OrchestratorRelay(
        conversation_id="conv-p1", run_id="run-p1", db_path=db_path,
        broadcaster=broadcaster, model=None, event_loop=loop, dashboard_port=8080,
    )

    import threading
    def _run_loop() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()
    loop_thread = threading.Thread(target=_run_loop, daemon=True)
    loop_thread.start()

    relay.start()
    time.sleep(0.3)
    relay.stop()
    loop.call_soon_threadsafe(loop.stop)
    loop_thread.join(timeout=2)

    history = get_workflow_chat_history(db_path, "run-p1")
    # Exactly one agent message with the assembled text.
    agent_msgs = [m for m in history if m["role"] == "agent"]
    assert len(agent_msgs) == 1, (
        f"expected 1 persisted agent message, got {len(agent_msgs)}: {history}"
    )
    assert agent_msgs[0]["content"] == "Hello, operator."
    # Conversation + session linkage persisted so conversation-view queries work.
    assert agent_msgs[0]["conversation_id"] == "conv-p1"
    assert agent_msgs[0]["session_id"] == relay.session_uuid

    loop.close()


@patch('subprocess.Popen')
def test_persistence_failure_does_not_break_sse_broadcast(mock_popen, tmp_path: Path):
    """If insert_chat_message blows up, the SSE broadcast must still fire.

    Persistence is best-effort; a DB-write failure (e.g. transient lock) must
    not drop the live user-visible response.
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from dag_dashboard.queries import insert_run
    insert_run(
        db_path=db_path, run_id="run-p2", workflow_name="wf", status="running",
        started_at="2026-05-04T00:00:00Z",
    )

    mock_process = MagicMock()
    mock_process.stdin = io.BytesIO()
    mock_process.stdout = io.StringIO(
        '{"type":"assistant","message":{"role":"assistant",'
        '"content":[{"type":"text","text":"still delivered"}]}}\n'
    )
    mock_process.stderr = io.BytesIO(b"")
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process

    loop = asyncio.new_event_loop()
    broadcaster = Mock()
    async def _publish(*args, **kwargs):
        return None
    broadcaster.publish = Mock(side_effect=_publish)

    relay = OrchestratorRelay(
        conversation_id="conv-p2", run_id="run-p2", db_path=db_path,
        broadcaster=broadcaster, model=None, event_loop=loop, dashboard_port=8080,
    )

    import threading
    def _run_loop() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()
    loop_thread = threading.Thread(target=_run_loop, daemon=True)
    loop_thread.start()

    # Force insert_chat_message to explode
    with patch("dag_dashboard.orchestrator_relay.insert_chat_message",
               side_effect=RuntimeError("db locked")):
        relay.start()
        time.sleep(0.3)
        relay.stop()

    loop.call_soon_threadsafe(loop.stop)
    loop_thread.join(timeout=2)

    # Broadcast still happened despite the failed persist.
    payloads = [c.args[1] for c in broadcaster.publish.call_args_list if len(c.args) >= 2]
    final = [p for p in payloads if p.get("type") == "chat_message"]
    assert len(final) == 1, f"expected 1 chat_message broadcast, got {len(final)}"
    assert final[0]["content"] == "still delivered"

    loop.close()


@patch('subprocess.Popen')
def test_partial_reply_flushed_on_subprocess_exit(mock_popen, tmp_path: Path):
    """Tokens streamed before a crash must be persisted on stdout_reader exit.

    Scenario: subprocess emits some text_delta events, then stdout closes
    without a final "assistant" event (simulates crash / TTL eviction /
    SIGKILL). The relay must flush the accumulated text with
    metadata.partial=true so the reply isn't lost on page reload.
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from dag_dashboard.queries import insert_run, insert_conversation, get_workflow_chat_history

    insert_conversation(db_path, "conv-flush", "dashboard", "2026-05-04T00:00:00Z")
    insert_run(
        db_path=db_path, run_id="run-flush", workflow_name="wf", status="running",
        started_at="2026-05-04T00:00:00Z", conversation_id="conv-flush",
    )

    # Two text_delta events, then stream ends (no assistant, no result).
    mock_process = MagicMock()
    mock_process.stdin = io.BytesIO()
    mock_process.stdout = io.StringIO(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        '{"type":"stream_event","event":{"type":"content_block_delta",'
        '"delta":{"type":"text_delta","text":"thinking about "}}}\n'
        '{"type":"stream_event","event":{"type":"content_block_delta",'
        '"delta":{"type":"text_delta","text":"your question"}}}\n'
    )
    mock_process.stderr = io.BytesIO(b"")
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process

    loop = asyncio.new_event_loop()
    broadcaster = Mock()
    async def _publish(*args, **kwargs):
        return None
    broadcaster.publish = Mock(side_effect=_publish)

    relay = OrchestratorRelay(
        conversation_id="conv-flush", run_id="run-flush", db_path=db_path,
        broadcaster=broadcaster, model=None, event_loop=loop, dashboard_port=8080,
    )

    import threading
    def _run_loop() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()
    loop_thread = threading.Thread(target=_run_loop, daemon=True)
    loop_thread.start()

    relay.start()
    time.sleep(0.3)  # reader exits after StringIO EOF, flush fires in finally
    relay.stop()
    loop.call_soon_threadsafe(loop.stop)
    loop_thread.join(timeout=2)

    history = get_workflow_chat_history(db_path, "run-flush")
    agent_msgs = [m for m in history if m["role"] == "agent"]
    assert len(agent_msgs) == 1, (
        f"expected 1 flushed agent message, got {len(agent_msgs)}: {history}"
    )
    assert agent_msgs[0]["content"] == "thinking about your question"
    # metadata is deserialized to a dict by _row_to_dict
    meta = agent_msgs[0].get("metadata") or {}
    assert meta.get("partial") is True
    assert meta.get("reason") == "stream_ended_without_final_assistant"

    loop.close()


@patch('subprocess.Popen')
def test_final_assistant_supersedes_partial_buffer(mock_popen, tmp_path: Path):
    """A final "assistant" event must consume the streaming buffer so the
    exit flush doesn't double-persist the same content.
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from dag_dashboard.queries import insert_run, insert_conversation, get_workflow_chat_history

    insert_conversation(db_path, "conv-nodup", "dashboard", "2026-05-04T00:00:00Z")
    insert_run(
        db_path=db_path, run_id="run-nodup", workflow_name="wf", status="running",
        started_at="2026-05-04T00:00:00Z", conversation_id="conv-nodup",
    )

    mock_process = MagicMock()
    mock_process.stdin = io.BytesIO()
    mock_process.stdout = io.StringIO(
        '{"type":"stream_event","event":{"type":"content_block_delta",'
        '"delta":{"type":"text_delta","text":"Hi"}}}\n'
        '{"type":"stream_event","event":{"type":"content_block_delta",'
        '"delta":{"type":"text_delta","text":" there"}}}\n'
        '{"type":"assistant","message":{"role":"assistant",'
        '"content":[{"type":"text","text":"Hi there"}]}}\n'
    )
    mock_process.stderr = io.BytesIO(b"")
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process

    loop = asyncio.new_event_loop()
    broadcaster = Mock()
    async def _publish(*args, **kwargs):
        return None
    broadcaster.publish = Mock(side_effect=_publish)

    relay = OrchestratorRelay(
        conversation_id="conv-nodup", run_id="run-nodup", db_path=db_path,
        broadcaster=broadcaster, model=None, event_loop=loop, dashboard_port=8080,
    )

    import threading
    def _run_loop() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()
    loop_thread = threading.Thread(target=_run_loop, daemon=True)
    loop_thread.start()

    relay.start()
    time.sleep(0.3)
    relay.stop()
    loop.call_soon_threadsafe(loop.stop)
    loop_thread.join(timeout=2)

    history = get_workflow_chat_history(db_path, "run-nodup")
    agent_msgs = [m for m in history if m["role"] == "agent"]
    # Exactly one row — final assistant persisted, exit flush was a no-op.
    assert len(agent_msgs) == 1, (
        f"final assistant + exit flush double-wrote: {agent_msgs}"
    )
    # And it's the final one, not tagged partial
    assert agent_msgs[0]["content"] == "Hi there"
    meta = agent_msgs[0].get("metadata") or {}
    assert not meta.get("partial"), "final row must not be flagged partial"

    loop.close()


@patch('subprocess.Popen')
def test_stderr_is_drained_to_prevent_pipe_deadlock(mock_popen, tmp_path: Path):
    """stderr is fully consumed by a dedicated drain thread.

    claude runs with --verbose and writes continuously to stderr. The OS
    pipe buffer is ~64 KB; once full, the subprocess blocks on its next
    stderr write and the orchestrator freezes mid-reply. The drain thread
    must fully consume whatever claude emits so the pipe is never back-
    pressured.
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from dag_dashboard.queries import insert_run
    insert_run(
        db_path=db_path, run_id="run-se", workflow_name="wf", status="running",
        started_at="2026-05-04T00:00:00Z",
    )

    # Simulate claude emitting a large stderr stream. If the drain stops
    # consuming, the subprocess would block — here we just verify every
    # byte is read from the pipe end by the time the thread exits.
    lines_written = 500
    stderr_bytes = (b"verbose diagnostic line " + b"x" * 200 + b"\n") * lines_written

    # Subclass BytesIO so we can count bytes actually returned by readline.
    # The drain thread closes the stream in its finally block, so we can't
    # rely on tell() after it exits. Tracking here gives us an independent
    # observable that survives close().
    class _CountingBytesIO(io.BytesIO):
        def __init__(self, data: bytes) -> None:
            super().__init__(data)
            self.bytes_read_out = 0

        def readline(self, size: int = -1) -> bytes:  # type: ignore[override]
            line = super().readline(size)
            self.bytes_read_out += len(line)
            return line

    mock_stderr = _CountingBytesIO(stderr_bytes)

    mock_process = MagicMock()
    mock_process.stdin = io.BytesIO()
    # Empty BytesIO for stdout so the stdout reader exits cleanly rather
    # than looping forever on StringIO's sentinel mismatch (readline()
    # returns '' not b'', so iter(readline, b'') never terminates).
    mock_process.stdout = io.BytesIO(b"")
    mock_process.stderr = mock_stderr
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process

    loop = asyncio.new_event_loop()
    relay = OrchestratorRelay(
        conversation_id="c-se", run_id="run-se", db_path=db_path,
        broadcaster=Mock(), model=None, event_loop=loop, dashboard_port=8080,
    )

    relay.start()
    stderr_thread = relay.stderr_thread
    assert stderr_thread is not None
    # Wait for the drain thread to exhaust the BytesIO and exit on its own.
    stderr_thread.join(timeout=3)
    assert not stderr_thread.is_alive(), "stderr drain thread did not exit"

    # Every byte the subprocess would have written must have been consumed.
    assert mock_stderr.bytes_read_out == len(stderr_bytes), (
        f"stderr not fully drained: read {mock_stderr.bytes_read_out}, "
        f"wrote {len(stderr_bytes)}"
    )

    relay.stop()
    loop.close()

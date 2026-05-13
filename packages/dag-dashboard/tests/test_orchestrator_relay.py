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
    relay.send_message("Hello orchestrator", "run-123")
    
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


# ---------------------------------------------------------------------------
# GW-5497 Phase 8: opt-in edit permissions
# ---------------------------------------------------------------------------


@patch('subprocess.Popen')
def test_allowed_tools_readonly_by_default(mock_popen, tmp_path: Path):
    """Without ``allow_edits``, argv must carry the analyst-only allowlist.

    Read-only mode is the back-compat default the original GW-5492
    implementation shipped with. Writing it into an assertion means a
    later refactor can't silently flip the default to edit mode.
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from dag_dashboard.queries import insert_run
    insert_run(
        db_path=db_path, run_id="ro", workflow_name="wf", status="running",
        started_at="2026-05-07T00:00:00Z",
    )
    mock_process = MagicMock()
    mock_process.stdin = io.BytesIO()
    mock_process.stdout = io.BytesIO(b"")
    mock_process.stderr = io.BytesIO(b"")
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process

    loop = asyncio.new_event_loop()
    relay = OrchestratorRelay(
        conversation_id="conv-ro", run_id="ro", db_path=db_path,
        broadcaster=Mock(), model=None, event_loop=loop, dashboard_port=8080,
        # allow_edits defaults to False
    )
    relay.start()
    relay.stop()

    argv = mock_popen.call_args.args[0]
    idx = argv.index("--allowedTools")
    assert argv[idx + 1] == "Bash,Read,Grep,Glob"
    assert "Write" not in argv[idx + 1]
    assert "Edit" not in argv[idx + 1]

    # System prompt carries the analyst-only footer.
    sp_idx = argv.index("--system-prompt")
    assert "analyst only" in argv[sp_idx + 1]
    assert "No Write, no Edit" in argv[sp_idx + 1]

    loop.close()


@patch('subprocess.Popen')
def test_allowed_tools_extended_when_allow_edits_true(mock_popen, tmp_path: Path):
    """``allow_edits=True`` adds Write + Edit and swaps the prompt footer.

    The edits footer must carry the scope rules (path-like channel, no
    dashboard self-edit) and the no-git-commit rule; otherwise granting
    tools without the instructions loses the safety framing.
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from dag_dashboard.queries import insert_run
    insert_run(
        db_path=db_path, run_id="rw", workflow_name="wf", status="running",
        started_at="2026-05-07T00:00:00Z",
    )
    mock_process = MagicMock()
    mock_process.stdin = io.BytesIO()
    mock_process.stdout = io.BytesIO(b"")
    mock_process.stderr = io.BytesIO(b"")
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process

    loop = asyncio.new_event_loop()
    relay = OrchestratorRelay(
        conversation_id="conv-rw", run_id="rw", db_path=db_path,
        broadcaster=Mock(), model=None, event_loop=loop, dashboard_port=8080,
        allow_edits=True,
    )
    relay.start()
    relay.stop()

    argv = mock_popen.call_args.args[0]
    idx = argv.index("--allowedTools")
    tools = argv[idx + 1]
    assert "Write" in tools
    assert "Edit" in tools
    assert "Bash" in tools and "Read" in tools
    assert tools == "Bash,Read,Write,Edit,Grep,Glob"

    # System prompt must carry the edits-enabled scope guidance — granting
    # tools without the rules would leave the orchestrator unconstrained.
    sp_idx = argv.index("--system-prompt")
    prompt = argv[sp_idx + 1]
    assert "You may propose and apply fixes" in prompt
    # Path-like channel scoping rule.
    assert "`workspace`" in prompt or "workspace" in prompt.lower()
    # Self-edit prohibition on the dashboard source.
    assert "packages/dag-dashboard/src/" in prompt
    # Git commit prohibition.
    assert "git commit" in prompt

    loop.close()


def test_build_system_prompt_includes_channel_values(tmp_path: Path):
    """Channel VALUES (not just keys) must reach the system prompt.

    Scoping the orchestrator to a workflow's workspace depends on the
    prompt carrying the path value — exposing only the keys gives the
    LLM nothing to work with. Stage a channel with a path-like value
    and assert the value round-trips into the rendered prompt.
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from dag_dashboard.queries import insert_run, get_connection

    insert_run(
        db_path=db_path, run_id="cv", workflow_name="wf", status="running",
        started_at="2026-05-07T00:00:00Z",
    )
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("cv", "workspace", "default",
         json.dumps("/Users/op/dev/skills-worktrees/GW-1234"),
         "2026-05-07T12:00:00Z"),
    )
    conn.commit()
    conn.close()

    loop = asyncio.new_event_loop()
    relay = OrchestratorRelay(
        conversation_id="conv-cv", run_id="cv", db_path=db_path,
        broadcaster=Mock(), model=None, event_loop=loop, dashboard_port=8080,
        allow_edits=True,
    )
    prompt = relay._build_system_prompt()
    assert "workspace" in prompt
    assert "/Users/op/dev/skills-worktrees/GW-1234" in prompt
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


@patch('subprocess.Popen')
def test_broadcast_routes_to_per_turn_run_id(mock_popen, tmp_path: Path):
    """SSE broadcasts use the run_id from send_message, not the spawn-time one.

    A conversation can be reused across multiple workflow runs via the
    continuation feature. The relay is spawned on run A but a follow-up
    message might arrive from run B's page. The reply must SSE-broadcast
    back to run B, not run A, so the user sees the response on the page
    they're actually viewing.
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from dag_dashboard.queries import insert_run
    insert_run(
        db_path=db_path, run_id="run-a", workflow_name="wf", status="running",
        started_at="2026-05-07T00:00:00Z",
    )
    insert_run(
        db_path=db_path, run_id="run-b", workflow_name="wf", status="running",
        started_at="2026-05-07T00:05:00Z",
    )

    # Deliver one assistant reply for each of the two user messages.
    # Crucial: claude only writes stdout AFTER receiving input. A vanilla
    # StringIO pre-loads both replies and the reader races ahead of the
    # second stdin write, defeating the per-turn invariant. Simulate the
    # real ordering with a stdin that reveals the next stdout chunk only
    # after a stdin write is observed.
    import threading as _threading

    reply1 = (
        '{"type":"assistant","message":{"role":"assistant",'
        '"content":[{"type":"text","text":"first reply"}]}}\n'
    )
    reply2 = (
        '{"type":"assistant","message":{"role":"assistant",'
        '"content":[{"type":"text","text":"second reply"}]}}\n'
    )

    class _PacedStdin(io.BytesIO):
        """Unblocks the next stdout chunk on each write."""
        def __init__(self, release: _threading.Event) -> None:
            super().__init__()
            self._release = release

        def write(self, data):  # type: ignore[override]
            n = super().write(data)
            self._release.set()
            return n

    class _PacedStdout:
        """Emits queued chunks lazily, one per release."""
        def __init__(self, chunks: list[str], release: _threading.Event) -> None:
            self._buffers = [c.encode() for c in chunks]
            self._release = release
            self._pos = b""

        def readline(self, *a, **kw):
            # Block until the paired stdin is written, then release one chunk.
            if not self._pos:
                if not self._buffers:
                    return b""
                # Wait for a signal from stdin, with a short timeout so EOF
                # also works.
                self._release.wait(timeout=2)
                self._release.clear()
                if not self._buffers:
                    return b""
                self._pos = self._buffers.pop(0)
            out, self._pos = self._pos, b""
            return out

        def close(self):
            self._buffers = []

    release = _threading.Event()
    mock_process = MagicMock()
    mock_process.stdin = _PacedStdin(release)
    mock_process.stdout = _PacedStdout([reply1, reply2], release)
    mock_process.stderr = io.BytesIO(b"")
    mock_process.poll.return_value = None
    mock_popen.return_value = mock_process

    loop = asyncio.new_event_loop()
    broadcaster = Mock()
    async def _publish(*args, **kwargs):
        return None
    broadcaster.publish = Mock(side_effect=_publish)

    relay = OrchestratorRelay(
        conversation_id="conv-ab",
        # Spawn-time run_id is run-a
        run_id="run-a",
        db_path=db_path, broadcaster=broadcaster, model=None,
        event_loop=loop, dashboard_port=8080,
    )

    import threading
    def _drive() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()
    loop_thread = threading.Thread(target=_drive, daemon=True)
    loop_thread.start()

    relay.start()

    # First turn originates on run-a (the "live" run at the moment).
    relay.send_message("hi from run-a", "run-a")
    time.sleep(0.15)

    # Second turn originates on run-b — user jumped to a new run but is
    # continuing the same conversation. The reply must broadcast to run-b.
    relay.send_message("hi from run-b", "run-b")
    time.sleep(0.3)

    relay.stop()
    loop.call_soon_threadsafe(loop.stop)
    loop_thread.join(timeout=2)

    # Each publish call is publish(run_id, payload). Collect (run_id, content).
    routed = [
        (c.args[0], c.args[1].get("content"))
        for c in broadcaster.publish.call_args_list
        if len(c.args) >= 2 and c.args[1].get("type") == "chat_message"
    ]
    # We expect the first final reply routed to run-a, second to run-b.
    assert routed == [("run-a", "first reply"), ("run-b", "second reply")], (
        f"per-turn routing failed: {routed}"
    )

    loop.close()


def test_system_prompt_includes_known_paths_block(tmp_path: Path):
    """GW-5912: prompt must include explicit `Known paths` with workspace + workflows_dir.

    Without this the agent does global filesystem walks (`find /`) trying to
    locate workflow YAML files. We inject the paths into every prompt so the
    agent never has to guess.
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from dag_dashboard.queries import insert_run, get_connection

    insert_run(
        db_path=db_path, run_id="kp", workflow_name="bug", status="paused",
        started_at="2026-05-13T00:00:00Z",
    )
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO channel_states (run_id, channel_key, channel_type, value_json, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("kp", "workspace", "default",
         json.dumps("/Users/op/.dag-dashboard/workspaces/kp"),
         "2026-05-13T12:00:00Z"),
    )
    conn.commit()
    conn.close()

    loop = asyncio.new_event_loop()
    relay = OrchestratorRelay(
        conversation_id="conv-kp", run_id="kp", db_path=db_path,
        broadcaster=Mock(), model=None, event_loop=loop, dashboard_port=8080,
        allow_edits=False,
        workflows_dirs=[Path("/Users/op/dev/skills/packages/dag-executor/workflows")],
    )
    prompt = relay._build_system_prompt()
    assert "Known paths:" in prompt
    assert "/Users/op/.dag-dashboard/workspaces/kp" in prompt
    assert "/Users/op/dev/skills/packages/dag-executor/workflows" in prompt
    loop.close()


def test_system_prompt_falls_back_when_workflows_dirs_unset(tmp_path: Path):
    """When no workflows_dirs is plumbed in, the prompt emits a placeholder
    that documents the unset state — not the literal `{workflows_dir}` token.
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from dag_dashboard.queries import insert_run

    insert_run(
        db_path=db_path, run_id="nws", workflow_name="bug", status="paused",
        started_at="2026-05-13T00:00:00Z",
    )

    loop = asyncio.new_event_loop()
    relay = OrchestratorRelay(
        conversation_id="conv-nws", run_id="nws", db_path=db_path,
        broadcaster=Mock(), model=None, event_loop=loop, dashboard_port=8080,
        allow_edits=False,
    )
    prompt = relay._build_system_prompt()
    assert "{workflows_dir}" not in prompt, (
        "Template placeholder leaked into prompt — fallback not applied"
    )
    assert "(not configured" in prompt
    loop.close()


def test_system_prompt_falls_back_when_workspace_channel_absent(tmp_path: Path):
    """When the workspace channel is missing, the prompt emits a placeholder
    instead of the literal `{workspace_path}` template token.
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from dag_dashboard.queries import insert_run

    insert_run(
        db_path=db_path, run_id="nows", workflow_name="bug", status="paused",
        started_at="2026-05-13T00:00:00Z",
    )

    loop = asyncio.new_event_loop()
    relay = OrchestratorRelay(
        conversation_id="conv-nows", run_id="nows", db_path=db_path,
        broadcaster=Mock(), model=None, event_loop=loop, dashboard_port=8080,
        allow_edits=False,
    )
    prompt = relay._build_system_prompt()
    assert "{workspace_path}" not in prompt
    assert "(not set" in prompt
    loop.close()


def test_system_prompt_default_is_explain_mode(tmp_path: Path):
    """GW-5912: prompt must steer the agent toward explaining from
    events + channel state instead of jumping straight to tool calls.

    Empty workspaces (workflows without `config.git`) are normal — the agent
    must not treat them as broken setups requiring investigation.
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from dag_dashboard.queries import insert_run

    insert_run(
        db_path=db_path, run_id="em", workflow_name="bug", status="paused",
        started_at="2026-05-13T00:00:00Z",
    )

    loop = asyncio.new_event_loop()
    relay = OrchestratorRelay(
        conversation_id="conv-em", run_id="em", db_path=db_path,
        broadcaster=Mock(), model=None, event_loop=loop, dashboard_port=8080,
        allow_edits=False,
    )
    prompt = relay._build_system_prompt()
    # Explain-first guidance is present.
    assert "default mode is EXPLAIN" in prompt or "EXPLAIN" in prompt
    # Empty workspace is documented as not-an-error.
    assert "empty by design" in prompt or "not a setup error" in prompt.lower()
    loop.close()


def test_system_prompt_forbids_global_find_walks(tmp_path: Path):
    """GW-5912: global filesystem walks (`find /`, `find ~`) cause multi-minute
    hangs. The prompt must explicitly prohibit them, in both readonly and
    edit footers (the agent reads whichever footer attaches to its run).
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)
    from dag_dashboard.queries import insert_run

    insert_run(
        db_path=db_path, run_id="nf", workflow_name="bug", status="paused",
        started_at="2026-05-13T00:00:00Z",
    )

    loop = asyncio.new_event_loop()
    for allow_edits in (False, True):
        relay = OrchestratorRelay(
            conversation_id=f"conv-nf-{allow_edits}", run_id="nf", db_path=db_path,
            broadcaster=Mock(), model=None, event_loop=loop, dashboard_port=8080,
            allow_edits=allow_edits,
        )
        prompt = relay._build_system_prompt()
        assert "find /" in prompt, (
            f"Prompt with allow_edits={allow_edits} must explicitly mention "
            "`find /` so the agent recognizes the prohibition."
        )
        assert "NEVER" in prompt
    loop.close()


def test_orchestrator_manager_passes_workflows_dirs_to_relay(tmp_path: Path):
    """OrchestratorManager.workflows_dirs must propagate to every spawned
    relay so the system prompt knows where the workflow YAML files live.
    """
    from dag_dashboard.orchestrator_manager import OrchestratorManager

    db_path = tmp_path / "test.db"
    init_db(db_path)

    mgr = OrchestratorManager(
        db_path=db_path,
        broadcaster=Mock(),
        workflows_dirs=[Path("/tmp/my-workflows-dir")],
    )
    assert mgr.workflows_dirs == [Path("/tmp/my-workflows-dir")]

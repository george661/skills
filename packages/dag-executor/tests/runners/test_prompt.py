"""Tests for prompt runner."""
from unittest.mock import MagicMock, patch
import io
import pytest

from dag_executor.schema import NodeDef, NodeStatus, ModelTier, OutputFormat
from dag_executor.runners.base import RunnerContext
from dag_executor.runners.prompt import PromptRunner


@pytest.fixture
def inline_prompt_node():
    """Create a prompt node with inline prompt."""
    return NodeDef(
        id="prompt1",
        name="Test Prompt",
        type="prompt",
        prompt="What is 2+2?",
        model=ModelTier.SONNET
    )


@pytest.fixture
def file_prompt_node():
    """Create a prompt node with prompt_file."""
    return NodeDef(
        id="prompt2",
        name="File Prompt",
        type="prompt",
        prompt_file="prompts/analyze.md",
        model=ModelTier.OPUS
    )


def test_prompt_inline_mode(inline_prompt_node):
    """Test inline prompt mode constructs correct CLI args."""
    ctx = RunnerContext(node_def=inline_prompt_node)

    mock_process = MagicMock()
    mock_process.stdout = io.StringIO("The answer is 4\n")
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
        runner = PromptRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.COMPLETED
        assert "answer" in result.output["response"].lower()

        # Verify dispatch-local.sh in ~/.claude/hooks/ was called
        call_args = mock_popen.call_args[0][0]
        assert any("hooks/dispatch-local.sh" in str(arg) for arg in call_args)
        # Inline prompts must use --prompt-stdin so the dispatcher reads stdin.
        assert "--prompt-stdin" in call_args


def test_prompt_file_mode(file_prompt_node, tmp_path, monkeypatch):
    """prompt_file contents are read from disk and fed to the subprocess on stdin.

    GW-5356: dispatch-local.sh never implemented --file; the old runner test
    encoded an aspirational contract. Under the unified model_invocation layer,
    both prompt_file and inline prompt end up as a single stdin payload — the
    transport is the same regardless of mode.
    """
    # Stage a real prompt file so the runner can read it.
    prompt_path = tmp_path / "analyze.md"
    prompt_path.write_text("ANALYZE THIS FILE")
    monkeypatch.setattr(file_prompt_node, "prompt_file", str(prompt_path))

    ctx = RunnerContext(node_def=file_prompt_node)

    mock_process = MagicMock()
    mock_process.stdout = io.StringIO("Analysis complete\n")
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
        runner = PromptRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.COMPLETED
        # Verify the file contents were written to stdin.
        mock_process.stdin.write.assert_called_with("ANALYZE THIS FILE")
        # Defense in depth: no dead --file flag lingering in the cmd.
        call_args = mock_popen.call_args[0][0]
        assert "--file" not in call_args


def test_prompt_model_tier_mapping():
    """Test model tier maps to correct --model flag."""
    # Test different model tiers
    for tier in [ModelTier.OPUS, ModelTier.SONNET, ModelTier.LOCAL]:
        node = NodeDef(
            id="p1",
            name="Prompt",
            type="prompt",
            prompt="test",
            model=tier
        )
        ctx = RunnerContext(node_def=node)

        mock_process = MagicMock()
        mock_process.stdout = io.StringIO("response\n")
        mock_process.stderr = MagicMock()
        mock_process.stderr.read.return_value = ""
        mock_process.stdin = MagicMock()
        mock_process.wait.return_value = 0

        with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
            runner = PromptRunner()
            runner.run(ctx)

            # Verify model flag was passed
            call_args = str(mock_popen.call_args[0][0])
            assert "--model" in call_args or tier.value in call_args


def test_prompt_dispatch_local_only(inline_prompt_node):
    """Test MVP dispatch is local only."""
    ctx = RunnerContext(node_def=inline_prompt_node)

    mock_process = MagicMock()
    mock_process.stdout = io.StringIO("response\n")
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
        runner = PromptRunner()
        runner.run(ctx)

        # Verify hooks/dispatch-local.sh was used
        call_args = mock_popen.call_args[0][0]
        assert any("hooks/dispatch-local.sh" in str(arg) for arg in call_args)


def test_prompt_subprocess_error(inline_prompt_node):
    """Test subprocess error handling."""
    ctx = RunnerContext(node_def=inline_prompt_node)

    mock_process = MagicMock()
    mock_process.stdout = io.StringIO("")
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = "CLI error"
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 1

    with patch("subprocess.Popen", return_value=mock_process):
        runner = PromptRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.FAILED
        assert "CLI error" in result.error


def test_prompt_captures_output(inline_prompt_node):
    """Test subprocess output is captured."""
    ctx = RunnerContext(node_def=inline_prompt_node)

    mock_process = MagicMock()
    mock_process.stdout = io.StringIO("Detailed response text\n")
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process):
        runner = PromptRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.COMPLETED
        assert "Detailed response text" in result.output["response"]


class TestTokenStreaming:
    """Test token streaming via Popen."""

    def test_prompt_streams_tokens_when_emitter_available(self):
        """Test that PromptRunner streams tokens line-by-line when event emitter is available."""
        from dag_executor.events import EventEmitter, EventType
        from unittest.mock import MagicMock
        import io

        node = NodeDef(
            id="prompt1",
            name="Test Prompt",
            type="prompt",
            prompt="What is 2+2?",
            model=ModelTier.SONNET
        )

        emitter = EventEmitter()
        stream_events = []

        def track_stream(event):
            if event.event_type == EventType.NODE_STREAM_TOKEN:
                stream_events.append(event)

        emitter.add_listener(track_stream)

        ctx = RunnerContext(node_def=node, event_emitter=emitter)

        # Mock Popen to simulate streaming output
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdout = io.StringIO("Line 1\nLine 2\nLine 3\n")

        def mock_wait(timeout=None):
            return 0

        mock_process.wait = mock_wait

        with patch("subprocess.Popen", return_value=mock_process):
            runner = PromptRunner()
            result = runner.run(ctx)

        # Verify result
        assert result.status == NodeStatus.COMPLETED
        assert "Line 1" in result.output["response"]
        assert "Line 2" in result.output["response"]
        assert "Line 3" in result.output["response"]

        # Verify streaming events were emitted
        assert len(stream_events) == 3
        assert "Line 1" in stream_events[0].metadata["token"]
        assert "Line 2" in stream_events[1].metadata["token"]
        assert "Line 3" in stream_events[2].metadata["token"]

    def test_prompt_backward_compat_without_emitter(self):
        """Test that PromptRunner still works without event emitter (backward compat)."""
        from unittest.mock import MagicMock
        import io

        node = NodeDef(
            id="prompt1",
            name="Test Prompt",
            type="prompt",
            prompt="What is 2+2?",
            model=ModelTier.SONNET
        )

        ctx = RunnerContext(node_def=node)  # No emitter

        # Mock Popen to simulate output
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdout = io.StringIO("The answer is 4\n")

        def mock_wait(timeout=None):
            return 0

        mock_process.wait = mock_wait

        with patch("subprocess.Popen", return_value=mock_process):
            runner = PromptRunner()
            result = runner.run(ctx)

        # Verify result (should still work without streaming)
        assert result.status == NodeStatus.COMPLETED
        assert "The answer is 4" in result.output["response"]

    def test_prompt_timeout_handling_with_popen(self):
        """Test that timeout handling works with Popen."""
        from unittest.mock import MagicMock
        import subprocess

        node = NodeDef(
            id="prompt1",
            name="Test Prompt",
            type="prompt",
            prompt="test",
            model=ModelTier.SONNET,
            timeout=1  # Short timeout
        )

        ctx = RunnerContext(node_def=node)

        # Mock Popen to simulate timeout
        mock_process = MagicMock()

        def mock_wait(timeout=None):
            raise subprocess.TimeoutExpired(cmd="test", timeout=timeout)

        mock_process.wait = mock_wait

        with patch("subprocess.Popen", return_value=mock_process):
            runner = PromptRunner()
            result = runner.run(ctx)

        # Verify timeout error
        assert result.status == NodeStatus.FAILED
        assert "timed out" in result.error.lower()


class TestPromptRunnerSessionContext:
    """Test prompt runner session context (GW-5304)."""
    
    @pytest.fixture
    def conversation_db(self, tmp_path):
        """Create a temporary SQLite database with schema."""
        db_path = tmp_path / "test.db"
        # Initialize schema
        from dag_dashboard.database import init_db
        init_db(db_path)
        return db_path
    
    @pytest.fixture
    def seeded_conversation(self, conversation_db):
        """Create a conversation with an active session and workflow run."""
        from dag_executor.conversations import start_conversation, mint_session
        import sqlite3

        conv = start_conversation(conversation_db, origin="test")
        session = mint_session(conversation_db, conv.id)

        # Create a workflow run so foreign key constraints work
        conn = sqlite3.connect(conversation_db)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO workflow_runs (id, workflow_name, status, started_at, conversation_id) VALUES (?, ?, ?, datetime('now'), ?)",
            ("run-123", "test-workflow", "running", conv.id)
        )
        conn.commit()
        conn.close()

        return conv.id, session.id
    
    def test_context_shared_resumes_active_session(self, conversation_db, seeded_conversation):
        """Test that context=shared reuses the same session across two prompts."""
        from dag_executor.schema import NodeDef, ModelTier, ContextMode
        from dag_executor.runners.prompt import PromptRunner
        from dag_executor.runners.base import RunnerContext
        
        conv_id, sess_id = seeded_conversation
        
        # First prompt with shared context
        node1 = NodeDef(
            id="prompt1",
            name="Prompt 1",
            type="prompt",
            prompt="First question",
            model=ModelTier.SONNET,
            context=ContextMode.SHARED
        )
        ctx1 = RunnerContext(
            node_def=node1,
            conversation_id=conv_id,
            db_path=conversation_db,
            workflow_id="run-123"
        )
        
        mock_process = MagicMock()
        mock_process.stdout = io.StringIO("Answer 1\n")
        mock_process.stderr = MagicMock()
        mock_process.stderr.read.return_value = ""
        mock_process.wait.return_value = 0
        
        with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
            runner = PromptRunner()
            result1 = runner.run(ctx1)
            
            assert result1.status == NodeStatus.COMPLETED
            call_args1 = mock_popen.call_args[0][0]
            # Should include --session-id flag with the active session
            assert "--session-id" in call_args1
            sid_index = call_args1.index("--session-id")
            session_id_1 = call_args1[sid_index + 1]
            assert session_id_1 == sess_id
        
        # Second prompt with shared context - should reuse same session
        node2 = NodeDef(
            id="prompt2",
            name="Prompt 2",
            type="prompt",
            prompt="Second question",
            model=ModelTier.SONNET,
            context=ContextMode.SHARED
        )
        ctx2 = RunnerContext(
            node_def=node2,
            conversation_id=conv_id,
            db_path=conversation_db,
            workflow_id="run-123"
        )
        
        mock_process2 = MagicMock()
        mock_process2.stdout = io.StringIO("Answer 2\n")
        mock_process2.stderr = MagicMock()
        mock_process2.stderr.read.return_value = ""
        mock_process2.wait.return_value = 0
        
        with patch("subprocess.Popen", return_value=mock_process2) as mock_popen2:
            result2 = runner.run(ctx2)
            
            assert result2.status == NodeStatus.COMPLETED
            call_args2 = mock_popen2.call_args[0][0]
            assert "--session-id" in call_args2
            sid_index2 = call_args2.index("--session-id")
            session_id_2 = call_args2[sid_index2 + 1]
            # Should be the SAME session ID
            assert session_id_2 == sess_id
    
    def test_context_shared_mints_if_no_active_session(self, conversation_db):
        """Test that context=shared mints a new session if none exists."""
        from dag_executor.conversations import start_conversation
        from dag_executor.schema import NodeDef, ModelTier, ContextMode
        from dag_executor.runners.prompt import PromptRunner
        from dag_executor.runners.base import RunnerContext
        
        # Create conversation with no active session
        conv = start_conversation(conversation_db, origin="test")
        
        node = NodeDef(
            id="prompt1",
            name="First Prompt",
            type="prompt",
            prompt="Question",
            model=ModelTier.SONNET,
            context=ContextMode.SHARED
        )
        ctx = RunnerContext(
            node_def=node,
            conversation_id=conv.id,
            db_path=conversation_db,
            workflow_id="run-123"
        )
        
        mock_process = MagicMock()
        mock_process.stdout = io.StringIO("Answer\n")
        mock_process.stderr = MagicMock()
        mock_process.stderr.read.return_value = ""
        mock_process.wait.return_value = 0
        
        with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
            runner = PromptRunner()
            result = runner.run(ctx)
            
            assert result.status == NodeStatus.COMPLETED
            call_args = mock_popen.call_args[0][0]
            # Should have created a session and passed --session-id
            assert "--session-id" in call_args
    
    def test_context_fresh_mints_chained_session(self, conversation_db, seeded_conversation):
        """Test that context=fresh creates a new session with parent_session_id chain."""
        from dag_executor.schema import NodeDef, ModelTier, ContextMode
        from dag_executor.runners.prompt import PromptRunner
        from dag_executor.runners.base import RunnerContext
        from dag_executor.conversations import get_active_session
        import sqlite3
        
        conv_id, old_sess_id = seeded_conversation
        
        node = NodeDef(
            id="prompt_fresh",
            name="Fresh Context Prompt",
            type="prompt",
            prompt="New context question",
            model=ModelTier.SONNET,
            context=ContextMode.FRESH
        )
        ctx = RunnerContext(
            node_def=node,
            conversation_id=conv_id,
            db_path=conversation_db,
            workflow_id="run-123"
        )
        
        mock_process = MagicMock()
        mock_process.stdout = io.StringIO("Fresh answer\n")
        mock_process.stderr = MagicMock()
        mock_process.stderr.read.return_value = ""
        mock_process.wait.return_value = 0
        
        with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
            runner = PromptRunner()
            result = runner.run(ctx)
            
            assert result.status == NodeStatus.COMPLETED
            call_args = mock_popen.call_args[0][0]
            # Should have a new session ID
            assert "--session-id" in call_args
            sid_index = call_args.index("--session-id")
            new_sess_id = call_args[sid_index + 1]
            assert new_sess_id != old_sess_id
        
        # Verify database state: old session is inactive, new session is active with parent
        conn = sqlite3.connect(conversation_db)
        cursor = conn.cursor()
        
        # Old session should be inactive
        cursor.execute("SELECT active FROM sessions WHERE id = ?", (old_sess_id,))
        old_active = cursor.fetchone()[0]
        assert old_active == 0
        
        # New session should be active with parent chain
        cursor.execute(
            "SELECT active, parent_session_id, transition_reason FROM sessions WHERE id = ?",
            (new_sess_id,)
        )
        row = cursor.fetchone()
        assert row[0] == 1  # active
        assert row[1] == old_sess_id  # parent_session_id
        assert row[2] == "fresh-context"  # transition_reason
        
        conn.close()
    
    def test_prompt_appends_user_and_assistant_messages(self, conversation_db, seeded_conversation):
        """Test that prompt runner appends both user and assistant messages."""
        from dag_executor.schema import NodeDef, ModelTier
        from dag_executor.runners.prompt import PromptRunner
        from dag_executor.runners.base import RunnerContext
        import sqlite3
        
        conv_id, sess_id = seeded_conversation
        
        node = NodeDef(
            id="prompt1",
            name="Test Prompt",
            type="prompt",
            prompt="Test question",
            model=ModelTier.SONNET
        )
        ctx = RunnerContext(
            node_def=node,
            conversation_id=conv_id,
            db_path=conversation_db,
            workflow_id="run-123"
        )
        
        mock_process = MagicMock()
        mock_process.stdout = io.StringIO("Test answer\n")
        mock_process.stderr = MagicMock()
        mock_process.stderr.read.return_value = ""
        mock_process.wait.return_value = 0
        
        with patch("subprocess.Popen", return_value=mock_process):
            runner = PromptRunner()
            result = runner.run(ctx)
            
            assert result.status == NodeStatus.COMPLETED
        
        # Check that 2 messages were appended
        conn = sqlite3.connect(conversation_db)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, conversation_id, session_id, run_id, execution_id FROM chat_messages WHERE conversation_id = ?",
            (conv_id,)
        )
        messages = cursor.fetchall()
        
        assert len(messages) == 2
        # First message should be user
        assert messages[0][0] == "user"
        assert messages[0][1] == conv_id
        assert messages[0][2] == sess_id
        assert messages[0][3] == "run-123"
        assert messages[0][4] is None  # execution_id set to None (no node_executions row)
        
        # Second message should be assistant
        assert messages[1][0] == "assistant"
        assert messages[1][1] == conv_id
        assert messages[1][2] == sess_id
        
        conn.close()
    
    def test_conversation_message_appended_event_emitted(self, conversation_db, seeded_conversation):
        """Test that CONVERSATION_MESSAGE_APPENDED events are emitted."""
        from dag_executor.schema import NodeDef, ModelTier
        from dag_executor.runners.prompt import PromptRunner
        from dag_executor.runners.base import RunnerContext
        from dag_executor.events import EventType
        
        conv_id, sess_id = seeded_conversation
        
        node = NodeDef(
            id="prompt1",
            name="Test Prompt",
            type="prompt",
            prompt="Test question",
            model=ModelTier.SONNET
        )
        
        # Mock event emitter
        mock_emitter = MagicMock()
        
        ctx = RunnerContext(
            node_def=node,
            conversation_id=conv_id,
            db_path=conversation_db,
            workflow_id="run-123",
            event_emitter=mock_emitter
        )
        
        mock_process = MagicMock()
        mock_process.stdout = io.StringIO("Test answer\n")
        mock_process.stderr = MagicMock()
        mock_process.stderr.read.return_value = ""
        mock_process.wait.return_value = 0
        
        with patch("subprocess.Popen", return_value=mock_process):
            runner = PromptRunner()
            result = runner.run(ctx)
            
            assert result.status == NodeStatus.COMPLETED
        
        # Should have emitted 2 CONVERSATION_MESSAGE_APPENDED events (user + assistant messages)
        # Filter for only CONVERSATION_MESSAGE_APPENDED events (not NODE_STREAM_TOKEN)
        call_args = mock_emitter.emit.call_args_list
        conversation_events = [call for call in call_args if call[0][0].event_type == EventType.CONVERSATION_MESSAGE_APPENDED]
        assert len(conversation_events) == 2
        
        # Check event structure
        event1 = conversation_events[0][0][0]  # First event
        assert event1.event_type == EventType.CONVERSATION_MESSAGE_APPENDED
        assert event1.metadata["role"] == "user"
        assert event1.metadata["conversation_id"] == conv_id
        assert event1.metadata["session_id"] == sess_id
        
        event2 = conversation_events[1][0][0]  # Second event
        assert event2.event_type == EventType.CONVERSATION_MESSAGE_APPENDED
        assert event2.metadata["role"] == "assistant"
    
    def test_prompt_skips_session_logic_when_no_db_path(self):
        """Test backward compatibility: skip session logic when no db_path."""
        from dag_executor.schema import NodeDef, ModelTier
        from dag_executor.runners.prompt import PromptRunner
        from dag_executor.runners.base import RunnerContext
        
        node = NodeDef(
            id="prompt1",
            name="Test Prompt",
            type="prompt",
            prompt="Test question",
            model=ModelTier.SONNET
        )
        # No conversation_id or db_path - old test path
        ctx = RunnerContext(node_def=node)
        
        mock_process = MagicMock()
        mock_process.stdout = io.StringIO("Test answer\n")
        mock_process.stderr = MagicMock()
        mock_process.stderr.read.return_value = ""
        mock_process.wait.return_value = 0
        
        with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
            runner = PromptRunner()
            result = runner.run(ctx)
            
            assert result.status == NodeStatus.COMPLETED
            call_args = mock_popen.call_args[0][0]
            # Should NOT include --session-id
            assert "--session-id" not in call_args

# GW-5308: Test output_format JSON spreading into output dict
def test_output_format_text_only_response_key():
    """Test that output_format=TEXT (or None) produces only {response: ...}."""
    node = NodeDef(
        id="prompt1",
        name="Text Prompt",
        type="prompt",
        prompt="What is 2+2?",
        model=ModelTier.SONNET,
        output_format=OutputFormat.TEXT
    )
    ctx = RunnerContext(node_def=node)

    mock_process = MagicMock()
    mock_process.stdout = io.StringIO("The answer is 4\n")
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process):
        runner = PromptRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.COMPLETED
        assert result.output == {"response": "The answer is 4\n"}
        # No other keys should exist
        assert len(result.output) == 1


def test_output_format_json_spreads_parsed_fields():
    """Test that output_format=JSON spreads parsed fields AND preserves response."""
    node = NodeDef(
        id="prompt1",
        name="JSON Prompt",
        type="prompt",
        prompt="Generate JSON",
        model=ModelTier.SONNET,
        output_format=OutputFormat.JSON
    )
    ctx = RunnerContext(node_def=node)

    json_output = '{"result": "success", "count": 42}\n'
    mock_process = MagicMock()
    mock_process.stdout = io.StringIO(json_output)
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process):
        runner = PromptRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.COMPLETED
        # Parsed fields should be spread
        assert result.output["result"] == "success"
        assert result.output["count"] == 42
        # Raw text should still be in response
        assert result.output["response"] == json_output


def test_output_format_json_invalid_json_fallback():
    """Test that invalid JSON with output_format=JSON falls back to text-only."""
    node = NodeDef(
        id="prompt1",
        name="JSON Prompt",
        type="prompt",
        prompt="Generate JSON",
        model=ModelTier.SONNET,
        output_format=OutputFormat.JSON
    )
    ctx = RunnerContext(node_def=node)

    # Invalid JSON output
    invalid_json = "This is not valid JSON\n"
    mock_process = MagicMock()
    mock_process.stdout = io.StringIO(invalid_json)
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process):
        runner = PromptRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.COMPLETED
        # Should fall back to text-only behavior
        assert result.output == {"response": invalid_json}


def test_output_format_json_collision_response_preserved():
    """Test that if parsed JSON contains 'response' key, raw text wins."""
    node = NodeDef(
        id="prompt1",
        name="JSON Prompt",
        type="prompt",
        prompt="Generate JSON",
        model=ModelTier.SONNET,
        output_format=OutputFormat.JSON
    )
    ctx = RunnerContext(node_def=node)

    # JSON that contains a "response" key
    json_output = '{"response": "parsed_value", "other": "data"}\n'
    mock_process = MagicMock()
    mock_process.stdout = io.StringIO(json_output)
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process):
        runner = PromptRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.COMPLETED
        # Raw text should win - backward compat guarantee
        assert result.output["response"] == json_output
        # Other parsed fields should still be present
        assert result.output["other"] == "data"


# ========== PROMPTC INTEGRATION TESTS ==========


def test_prompt_file_with_promptc_loads_mode_b_body(tmp_path):
    """Test that promptc renders the file in mode-B with input substitution."""
    fixture_path = tmp_path / "simple.md"
    fixture_path.write_text(
        '{% input name="topic" type="string" /%}\n'
        'Analyze {% $inputs.topic %}.'
    )
    
    node = NodeDef(
        id="prompt_promptc",
        name="Promptc Test",
        type="prompt",
        prompt_file=str(fixture_path),
        prompt_inputs={"topic": "AI"},
        model=ModelTier.SONNET
    )
    ctx = RunnerContext(node_def=node)

    mock_process = MagicMock()
    mock_process.stdout = io.StringIO("Analysis result\n")
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
        runner = PromptRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.COMPLETED
        # Verify the stdin fed to the model subprocess
        mock_process.stdin.write.assert_called_once()
        written_stdin = mock_process.stdin.write.call_args[0][0]
        # Input declarations should be stripped, substitution applied
        assert "input name=" not in written_stdin
        assert "Analyze AI." in written_stdin


def test_prompt_file_hoists_bash_run(tmp_path):
    """Test that hoisted bash runs execute before model invocation."""
    fixture_path = tmp_path / "bash_run.md"
    fixture_path.write_text(
        '{% run id="count" bash="echo 42" /%}\n'
        'The count is $count.'
    )
    
    node = NodeDef(
        id="prompt_bash",
        name="Bash Run Test",
        type="prompt",
        prompt_file=str(fixture_path),
        model=ModelTier.SONNET
    )
    ctx = RunnerContext(node_def=node)

    # Track subprocess calls
    calls = []
    
    def side_effect(*args, **kwargs):
        mock_proc = MagicMock()
        # First call is bash run, second is model invocation
        if len(calls) == 0:  # bash run
            mock_proc.communicate.return_value = ("42\n", "")
            mock_proc.returncode = 0
        else:  # model invocation
            mock_proc.stdout = io.StringIO("Model response\n")
            mock_proc.stderr = MagicMock()
            mock_proc.stderr.read.return_value = ""
            mock_proc.wait.return_value = 0
        mock_proc.stdin = MagicMock()
        calls.append((args, kwargs))
        return mock_proc
    
    with patch("subprocess.Popen", side_effect=side_effect):
        runner = PromptRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.COMPLETED
        # Verify bash was called first
        assert len(calls) == 2
        # First call should be for bash
        assert "bash" in str(calls[0])
        # Model call should have substituted $count
        # (check via stdin write to second process)


def test_prompt_file_hoists_skill_run(tmp_path):
    """Test that hoisted skill runs execute and outputs are captured as JSON."""
    fixture_path = tmp_path / "skill_run.md"
    fixture_path.write_text(
        '{% run id="meta" skill="jira/get_issue" capture="json" %}'
        '{"issue_key": "GW-1"}'
        '{% /run %}\n'
        'Issue status: $meta.status'
    )
    
    node = NodeDef(
        id="prompt_skill",
        name="Skill Run Test",
        type="prompt",
        prompt_file=str(fixture_path),
        model=ModelTier.SONNET
    )
    ctx = RunnerContext(node_def=node)

    calls = []
    
    def side_effect(*args, **kwargs):
        mock_proc = MagicMock()
        if len(calls) == 0:  # skill run
            mock_proc.communicate.return_value = ('{"status": "Done"}\n', "")
            mock_proc.returncode = 0
        else:  # model invocation
            mock_proc.stdout = io.StringIO("Model response\n")
            mock_proc.stderr = MagicMock()
            mock_proc.stderr.read.return_value = ""
            mock_proc.wait.return_value = 0
        mock_proc.stdin = MagicMock()
        calls.append((args, kwargs))
        return mock_proc
    
    # Patch os.path.exists so the skill-path resolver doesn't reject CI runners
    # that have no ~/.claude/skills/ staged. The real resolver shells out to
    # `npx tsx <path>` — the subprocess itself is mocked by side_effect.
    with patch("subprocess.Popen", side_effect=side_effect), \
         patch("dag_executor.runners.prompt.os.path.exists", return_value=True):
        runner = PromptRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.COMPLETED
        # Verify skill was called (should contain npx tsx)
        assert len(calls) == 2


def test_prompt_file_parse_output_populates_writes(tmp_path):
    """Test that contract-tier output parsing populates write channels."""
    fixture_path = tmp_path / "contract.md"
    fixture_path.write_text(
        '{% meta tier="contract" /%}\n'
        '{% output name="verdict" type="enum" values=["APPROVED", "REJECTED"] /%}\n'
        'Review this and output your verdict.\n'
        'Your response must include:\n'
        'VERDICT: [APPROVED or REJECTED]'
    )
    
    node = NodeDef(
        id="prompt_contract",
        name="Contract Test",
        type="prompt",
        prompt_file=str(fixture_path),
        writes=["verdict"],
        model=ModelTier.SONNET
    )
    ctx = RunnerContext(node_def=node)

    mock_process = MagicMock()
    # Model response with verdict (field name is case-sensitive)
    mock_process.stdout = io.StringIO("After review:\nverdict: APPROVED\n")
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process):
        runner = PromptRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.COMPLETED
        # Verify parsed field is in output
        assert "verdict" in result.output
        assert result.output["verdict"] == "APPROVED"


def test_prompt_file_parse_output_error_fails_node(tmp_path):
    """Test that parse_output validation errors fail the node."""
    fixture_path = tmp_path / "contract.md"
    fixture_path.write_text(
        '{% meta tier="contract" /%}\n'
        '{% output name="verdict" type="enum" values=["APPROVED", "REJECTED"] /%}\n'
        'Review this and output your verdict.'
    )
    
    node = NodeDef(
        id="prompt_contract_fail",
        name="Contract Fail Test",
        type="prompt",
        prompt_file=str(fixture_path),
        writes=["verdict"],
        model=ModelTier.SONNET
    )
    ctx = RunnerContext(node_def=node)

    mock_process = MagicMock()
    # Invalid enum value (field name is case-sensitive)
    mock_process.stdout = io.StringIO("verdict: MAYBE\n")
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process):
        runner = PromptRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.FAILED
        assert "verdict" in result.error.lower() or "enum" in result.error.lower()


def test_prompt_file_hoisted_run_failure_fails_node(tmp_path):
    """Test that non-zero exit from hoisted run fails the prompt node."""
    fixture_path = tmp_path / "failing_bash.md"
    fixture_path.write_text(
        '{% run id="fail" bash="exit 1" /%}\n'
        'This should not execute.'
    )
    
    node = NodeDef(
        id="prompt_fail_bash",
        name="Failing Bash Test",
        type="prompt",
        prompt_file=str(fixture_path),
        model=ModelTier.SONNET
    )
    ctx = RunnerContext(node_def=node)

    def side_effect(*args, **kwargs):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "exit status 1")
        mock_proc.returncode = 1
        mock_proc.stdin = MagicMock()
        return mock_proc
    
    with patch("subprocess.Popen", side_effect=side_effect):
        runner = PromptRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.FAILED
        assert "fail" in result.error.lower() or "exit" in result.error.lower()


def test_prompt_file_unsupported_run_shape_fails_node(tmp_path):
    """Test that unsupported run shapes (tool/command/prompt_file) fail gracefully."""
    fixture_path = tmp_path / "unsupported.md"
    fixture_path.write_text(
        '{% run id="unsup" tool="whatever" /%}\n'
        'Should fail.'
    )
    
    node = NodeDef(
        id="prompt_unsupported",
        name="Unsupported Run Test",
        type="prompt",
        prompt_file=str(fixture_path),
        model=ModelTier.SONNET
    )
    ctx = RunnerContext(node_def=node)

    runner = PromptRunner()
    result = runner.run(ctx)

    assert result.status == NodeStatus.FAILED
    assert "not yet supported" in result.error.lower() or "not implemented" in result.error.lower()


def test_prompt_file_parse_error_fails_node(tmp_path):
    """Test that malformed promptc syntax fails the node with parse error."""
    fixture_path = tmp_path / "malformed.md"
    fixture_path.write_text(
        '{% meta\n'
        'This is intentionally unclosed'
    )
    
    node = NodeDef(
        id="prompt_malformed",
        name="Malformed Test",
        type="prompt",
        prompt_file=str(fixture_path),
        model=ModelTier.SONNET
    )
    ctx = RunnerContext(node_def=node)

    runner = PromptRunner()
    result = runner.run(ctx)

    assert result.status == NodeStatus.FAILED
    assert "parse" in result.error.lower()

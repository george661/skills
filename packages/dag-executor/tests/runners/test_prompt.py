"""Tests for prompt runner."""
from unittest.mock import MagicMock, patch
import io
import pytest

from dag_executor.schema import NodeDef, NodeStatus, ModelTier
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


def test_prompt_file_mode(file_prompt_node):
    """Test prompt_file mode constructs correct CLI args."""
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
        call_args = mock_popen.call_args[0][0]
        # prompt_file → --file <path>, no stdin flag.
        assert "--file" in call_args
        assert "prompts/analyze.md" in call_args
        assert "--prompt-stdin" not in call_args


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

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

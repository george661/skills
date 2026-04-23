"""Tests for bash runner."""
from unittest.mock import AsyncMock, Mock, patch
import asyncio
import pytest

from dag_executor.schema import NodeDef, NodeStatus
from dag_executor.runners.base import RunnerContext
from dag_executor.runners.bash import BashRunner


def _create_mock_subprocess_exec(stdout_lines=None, stderr_lines=None, returncode=0):
    """Create a mock async subprocess_exec function with configurable output.

    Args:
        stdout_lines: List of strings (lines) to return from stdout
        stderr_lines: List of strings (lines) to return from stderr
        returncode: Process exit code

    Returns:
        Async function that returns a mock process
    """
    if stdout_lines is None:
        stdout_lines = []
    if stderr_lines is None:
        stderr_lines = []

    # Convert lines to bytes and add EOF marker
    stdout_bytes = [line.encode('utf-8') if isinstance(line, str) else line for line in stdout_lines] + [b'']
    stderr_bytes = [line.encode('utf-8') if isinstance(line, str) else line for line in stderr_lines] + [b'']

    async def mock_create_subprocess_exec(*args, **kwargs):
        # Store call info for later verification
        mock_create_subprocess_exec.call_args = (args, kwargs)
        mock_create_subprocess_exec.call_count += 1

        # Create async stream readers
        stdout_reader = AsyncMock()
        stderr_reader = AsyncMock()
        stdout_reader.readline = AsyncMock(side_effect=stdout_bytes.copy())
        stderr_reader.readline = AsyncMock(side_effect=stderr_bytes.copy())

        # Create mock process
        process = AsyncMock()
        process.stdout = stdout_reader
        process.stderr = stderr_reader
        process.returncode = returncode
        process.wait = AsyncMock(return_value=returncode)
        process.kill = Mock()

        return process

    mock_create_subprocess_exec.call_args = None
    mock_create_subprocess_exec.call_count = 0

    return mock_create_subprocess_exec


@pytest.fixture
def bash_node():
    """Create a bash node definition."""
    return NodeDef(
        id="bash1",
        name="Test Bash",
        type="bash",
        script="echo 'Hello World'"
    )


@pytest.mark.asyncio
async def test_bash_runner_executes_script(bash_node):
    """Test bash runner executes script and captures output."""
    ctx = RunnerContext(
        node_def=bash_node,
        resolved_inputs={"name": "Alice", "count": 42}
    )

    mock_subprocess = _create_mock_subprocess_exec(
        stdout_lines=["Hello World\n"],
        stderr_lines=[],
        returncode=0
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        runner = BashRunner()
        result = await runner._run_async(ctx)

        assert result.status == NodeStatus.COMPLETED
        assert result.output["stdout"] == "Hello World\n"
        assert result.error is None

        # Verify subprocess was called
        assert mock_subprocess.call_count == 1
        call_args = mock_subprocess.call_args[0]
        assert call_args[0] == "bash"
        assert call_args[1] == "-c"


@pytest.mark.asyncio
async def test_bash_variables_passed_as_env_vars(bash_node):
    """Test variables are passed as DAG_ prefixed environment variables."""
    ctx = RunnerContext(
        node_def=bash_node,
        resolved_inputs={"name": "Bob", "age": 30}
    )

    mock_subprocess = _create_mock_subprocess_exec(returncode=0)

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        runner = BashRunner()
        await runner._run_async(ctx)

        # Verify env vars were set
        call_kwargs = mock_subprocess.call_args[1]
        env = call_kwargs.get("env", {})
        assert "DAG_NAME" in env
        assert env["DAG_NAME"] == "Bob"
        assert "DAG_AGE" in env
        assert env["DAG_AGE"] == "30"


@pytest.mark.asyncio
async def test_bash_timeout_enforced(bash_node):
    """Test timeout enforcement."""
    bash_node.timeout = 5
    ctx = RunnerContext(node_def=bash_node)

    mock_subprocess = _create_mock_subprocess_exec(returncode=0)

    async def mock_wait_for(*args, **kwargs):
        raise asyncio.TimeoutError()

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess), \
         patch("asyncio.wait_for", side_effect=mock_wait_for):
        runner = BashRunner()
        result = await runner._run_async(ctx)

        assert result.status == NodeStatus.FAILED
        assert "timeout" in result.error.lower() or "timed out" in result.error.lower()


@pytest.mark.asyncio
async def test_bash_output_size_limit(bash_node):
    """Test output size limit is enforced."""
    ctx = RunnerContext(
        node_def=bash_node,
        max_output_bytes=100  # Small limit for testing
    )

    # Create lines that will exceed the limit
    large_output_lines = ["x" * 50 + "\n", "y" * 60 + "\n"]
    mock_subprocess = _create_mock_subprocess_exec(
        stdout_lines=large_output_lines,
        returncode=0
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        runner = BashRunner()
        result = await runner._run_async(ctx)

        assert result.status == NodeStatus.FAILED
        assert "output size limit" in result.error.lower()


@pytest.mark.asyncio
async def test_bash_non_zero_exit_returns_failed(bash_node):
    """Test non-zero exit code returns FAILED status."""
    ctx = RunnerContext(node_def=bash_node)

    mock_subprocess = _create_mock_subprocess_exec(
        stdout_lines=[],
        stderr_lines=["Command failed\n"],
        returncode=1
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        runner = BashRunner()
        result = await runner._run_async(ctx)

        assert result.status == NodeStatus.FAILED
        assert result.error == "Command failed\n"


@pytest.mark.asyncio
async def test_bash_captures_stdout_and_stderr(bash_node):
    """Test stdout and stderr are both captured."""
    ctx = RunnerContext(node_def=bash_node)

    mock_subprocess = _create_mock_subprocess_exec(
        stdout_lines=["Standard output\n"],
        stderr_lines=["Standard error\n"],
        returncode=0
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        runner = BashRunner()
        result = await runner._run_async(ctx)

        assert result.status == NodeStatus.COMPLETED
        assert result.output["stdout"] == "Standard output\n"
        assert result.output["stderr"] == "Standard error\n"


@pytest.mark.asyncio
async def test_bash_log_line_includes_stream_tag(bash_node):
    """Test that NODE_LOG_LINE events include stream tag (stdout/stderr)."""
    from dag_executor.events import EventEmitter, EventType

    emitter = EventEmitter()
    events = []
    emitter.add_listener(lambda e: events.append(e))

    ctx = RunnerContext(
        node_def=bash_node,
        workflow_id="test_workflow",
        event_emitter=emitter
    )

    mock_subprocess = _create_mock_subprocess_exec(
        stdout_lines=["stdout line 1\n", "stdout line 2\n"],
        stderr_lines=["stderr line 1\n"],
        returncode=0
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        runner = BashRunner()
        result = await runner._run_async(ctx)

        assert result.status == NodeStatus.COMPLETED

        # Filter to log line events
        log_events = [e for e in events if e.event_type == EventType.NODE_LOG_LINE]
        assert len(log_events) == 3

        # Check stream tags
        assert log_events[0].metadata["stream"] == "stdout"
        assert log_events[0].metadata["line"] == "stdout line 1"
        assert log_events[1].metadata["stream"] == "stdout"
        assert log_events[1].metadata["line"] == "stdout line 2"
        assert log_events[2].metadata["stream"] == "stderr"
        assert log_events[2].metadata["line"] == "stderr line 1"


@pytest.mark.asyncio
async def test_bash_log_line_sequence_monotonic(bash_node):
    """Test that NODE_LOG_LINE events have monotonically increasing sequence numbers."""
    from dag_executor.events import EventEmitter, EventType

    emitter = EventEmitter()
    events = []
    emitter.add_listener(lambda e: events.append(e))

    ctx = RunnerContext(
        node_def=bash_node,
        workflow_id="test_workflow",
        event_emitter=emitter
    )

    mock_subprocess = _create_mock_subprocess_exec(
        stdout_lines=["line 1\n", "line 2\n"],
        stderr_lines=["error 1\n"],
        returncode=0
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        runner = BashRunner()
        result = await runner._run_async(ctx)

        assert result.status == NodeStatus.COMPLETED

        # Filter to log line events
        log_events = [e for e in events if e.event_type == EventType.NODE_LOG_LINE]
        assert len(log_events) == 3

        # Check sequences are monotonic
        sequences = [e.metadata["sequence"] for e in log_events]
        assert sequences == [0, 1, 2]


@pytest.mark.asyncio
async def test_bash_mixed_stdout_stderr_preserves_stream_order(bash_node):
    """Test that mixed stdout/stderr is preserved within each stream."""
    from dag_executor.events import EventEmitter, EventType

    emitter = EventEmitter()
    events = []
    emitter.add_listener(lambda e: events.append(e))

    ctx = RunnerContext(
        node_def=bash_node,
        workflow_id="test_workflow",
        event_emitter=emitter
    )

    # Interleaved output
    mock_subprocess = _create_mock_subprocess_exec(
        stdout_lines=["stdout A\n", "stdout B\n", "stdout C\n"],
        stderr_lines=["stderr 1\n", "stderr 2\n"],
        returncode=0
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        runner = BashRunner()
        result = await runner._run_async(ctx)

        assert result.status == NodeStatus.COMPLETED

        # Filter to log line events
        log_events = [e for e in events if e.event_type == EventType.NODE_LOG_LINE]

        # Separate by stream
        stdout_events = [e for e in log_events if e.metadata["stream"] == "stdout"]
        stderr_events = [e for e in log_events if e.metadata["stream"] == "stderr"]

        # Check stdout order preserved
        assert len(stdout_events) == 3
        assert stdout_events[0].metadata["line"] == "stdout A"
        assert stdout_events[1].metadata["line"] == "stdout B"
        assert stdout_events[2].metadata["line"] == "stdout C"

        # Check stderr order preserved
        assert len(stderr_events) == 2
        assert stderr_events[0].metadata["line"] == "stderr 1"
        assert stderr_events[1].metadata["line"] == "stderr 2"


@pytest.mark.asyncio
async def test_bash_script_substitution():
    """Test that script body substitution from resolved_inputs works."""
    bash_node = NodeDef(
        id="greet",
        name="Greet",
        type="bash",
        script="echo 'Hello $name'"  # Raw script with unsubstituted variable
    )

    # resolved_inputs contains the substituted script body
    ctx = RunnerContext(
        node_def=bash_node,
        resolved_inputs={
            "script": "echo 'Hello Alice'",  # Resolved script body
            "name": "Alice"
        }
    )

    mock_subprocess = _create_mock_subprocess_exec(
        stdout_lines=["Hello Alice\n"],
        returncode=0
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        runner = BashRunner()
        result = await runner._run_async(ctx)

        assert result.status == NodeStatus.COMPLETED

        # Verify subprocess was called with the RESOLVED script body, not raw node_def.script
        call_args = mock_subprocess.call_args[0]
        assert call_args[0] == "bash"
        assert call_args[1] == "-c"
        assert call_args[2] == "echo 'Hello Alice'", \
            "Script body should be resolved from ctx.resolved_inputs['script'], not ctx.node_def.script"


@pytest.mark.asyncio
async def test_bash_live_streaming_1hz_for_10s():
    """Integration test: verify live streaming with real subprocess outputting 1 line/sec for 10 seconds.

    This is a slow test (~10s) that verifies the streaming behavior works with a real subprocess.
    """
    import time
    from dag_executor.events import EventEmitter, EventType

    # Create a bash script that outputs 1 line per second for 10 seconds
    script = """
    for i in {1..10}; do
        echo "Line $i"
        sleep 1
    done
    """

    bash_node = NodeDef(
        id="streaming_test",
        name="Streaming Test",
        type="bash",
        script=script,
        timeout=15  # Give extra time for test overhead
    )

    emitter = EventEmitter()
    events = []
    event_times = []

    def record_event(e):
        events.append(e)
        event_times.append(time.time())

    emitter.add_listener(record_event)

    ctx = RunnerContext(
        node_def=bash_node,
        workflow_id="streaming_test",
        event_emitter=emitter
    )

    runner = BashRunner()
    start_time = time.time()
    result = await runner._run_async(ctx)
    total_time = time.time() - start_time

    assert result.status == NodeStatus.COMPLETED

    # Filter to log line events
    log_events = [e for e in events if e.event_type == EventType.NODE_LOG_LINE]
    assert len(log_events) == 10

    # Check all lines are present
    for i, event in enumerate(log_events, 1):
        assert event.metadata["line"] == f"Line {i}"
        assert event.metadata["stream"] == "stdout"
        assert event.metadata["sequence"] == i - 1

    # Verify the script ran for approximately 10 seconds
    assert 9.5 <= total_time <= 12.0, f"Expected ~10s execution, got {total_time:.1f}s"

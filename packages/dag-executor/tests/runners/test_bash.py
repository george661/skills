"""Tests for bash runner."""
from unittest.mock import Mock, patch
import pytest
import subprocess

from dag_executor.schema import NodeDef, NodeStatus
from dag_executor.runners.base import RunnerContext
from dag_executor.runners.bash import BashRunner


@pytest.fixture
def bash_node():
    """Create a bash node definition."""
    return NodeDef(
        id="bash1",
        name="Test Bash",
        type="bash",
        script="echo 'Hello World'"
    )


def _mock_popen(stdout: str = "", stderr: str = "", returncode: int = 0, timeout_exc: bool = False):
    """Build a Mock Popen that .communicate() returns (stdout, stderr) and sets returncode.

    If timeout_exc=True, .communicate() raises subprocess.TimeoutExpired.
    """
    proc = Mock()
    proc.returncode = returncode
    if timeout_exc:
        proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="bash", timeout=5)
    else:
        proc.communicate.return_value = (stdout, stderr)
    return proc


def test_bash_runner_executes_script(bash_node):
    """Test bash runner executes script and captures output."""
    ctx = RunnerContext(
        node_def=bash_node,
        resolved_inputs={"name": "Alice", "count": 42}
    )

    proc = _mock_popen(stdout="Hello World\n", stderr="", returncode=0)

    with patch("dag_executor.runners.bash.subprocess.Popen", return_value=proc) as mock_popen:
        runner = BashRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.COMPLETED
        assert result.output["stdout"] == "Hello World\n"
        assert result.error is None

        # Verify subprocess was called
        mock_popen.assert_called_once()
        assert "bash" in mock_popen.call_args[0][0]


def test_bash_variables_passed_as_env_vars(bash_node):
    """Test variables are passed as DAG_ prefixed environment variables."""
    ctx = RunnerContext(
        node_def=bash_node,
        resolved_inputs={"name": "Bob", "age": 30}
    )

    proc = _mock_popen(stdout="", stderr="", returncode=0)

    with patch("dag_executor.runners.bash.subprocess.Popen", return_value=proc) as mock_popen:
        runner = BashRunner()
        runner.run(ctx)

        # Verify env vars were set
        call_kwargs = mock_popen.call_args[1]
        env = call_kwargs.get("env", {})
        assert "DAG_NAME" in env
        assert env["DAG_NAME"] == "Bob"
        assert "DAG_AGE" in env
        assert env["DAG_AGE"] == "30"


def test_bash_timeout_enforced(bash_node):
    """Test timeout enforcement."""
    bash_node.timeout = 5
    ctx = RunnerContext(node_def=bash_node)

    proc = _mock_popen(timeout_exc=True)

    with patch("dag_executor.runners.bash.subprocess.Popen", return_value=proc):
        runner = BashRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.FAILED
        assert "timeout" in result.error.lower() or "timed out" in result.error.lower()


def test_bash_output_size_limit(bash_node):
    """Test output size limit is enforced."""
    ctx = RunnerContext(
        node_def=bash_node,
        max_output_bytes=100  # Small limit for testing
    )

    large_output = "x" * 200  # Exceeds limit
    proc = _mock_popen(stdout=large_output, stderr="", returncode=0)

    with patch("dag_executor.runners.bash.subprocess.Popen", return_value=proc):
        runner = BashRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.FAILED
        assert "output size limit" in result.error.lower()


def test_bash_non_zero_exit_returns_failed(bash_node):
    """Test non-zero exit code returns FAILED status."""
    ctx = RunnerContext(node_def=bash_node)

    proc = _mock_popen(stdout="", stderr="Command failed", returncode=1)

    with patch("dag_executor.runners.bash.subprocess.Popen", return_value=proc):
        runner = BashRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.FAILED
        assert result.error == "Command failed"


def test_bash_captures_stdout_and_stderr(bash_node):
    """Test stdout and stderr are both captured."""
    ctx = RunnerContext(node_def=bash_node)

    proc = _mock_popen(stdout="Standard output", stderr="Standard error", returncode=0)

    with patch("dag_executor.runners.bash.subprocess.Popen", return_value=proc):
        runner = BashRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.COMPLETED
        assert result.output["stdout"] == "Standard output"
        assert result.output["stderr"] == "Standard error"

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


def test_bash_runner_executes_script(bash_node):
    """Test bash runner executes script and captures output."""
    ctx = RunnerContext(
        node_def=bash_node,
        resolved_inputs={"name": "Alice", "count": 42}
    )
    
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Hello World\n"
    mock_result.stderr = ""
    
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        runner = BashRunner()
        result = runner.run(ctx)
        
        assert result.status == NodeStatus.COMPLETED
        assert result.output["stdout"] == "Hello World\n"
        assert result.error is None
        
        # Verify subprocess was called
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert "bash" in mock_run.call_args[0][0]
        assert call_kwargs.get("capture_output") is True


def test_bash_variables_passed_as_env_vars(bash_node):
    """Test variables are passed as DAG_ prefixed environment variables."""
    ctx = RunnerContext(
        node_def=bash_node,
        resolved_inputs={"name": "Bob", "age": 30}
    )
    
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""
    
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        runner = BashRunner()
        runner.run(ctx)
        
        # Verify env vars were set
        call_kwargs = mock_run.call_args[1]
        env = call_kwargs.get("env", {})
        assert "DAG_NAME" in env
        assert env["DAG_NAME"] == "Bob"
        assert "DAG_AGE" in env
        assert env["DAG_AGE"] == "30"


def test_bash_timeout_enforced(bash_node):
    """Test timeout enforcement."""
    bash_node.timeout = 5
    ctx = RunnerContext(node_def=bash_node)
    
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("bash", 5)):
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
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = large_output
    mock_result.stderr = ""
    
    with patch("subprocess.run", return_value=mock_result):
        runner = BashRunner()
        result = runner.run(ctx)
        
        assert result.status == NodeStatus.FAILED
        assert "output size limit" in result.error.lower()


def test_bash_non_zero_exit_returns_failed(bash_node):
    """Test non-zero exit code returns FAILED status."""
    ctx = RunnerContext(node_def=bash_node)
    
    mock_result = Mock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "Command failed"
    
    with patch("subprocess.run", return_value=mock_result):
        runner = BashRunner()
        result = runner.run(ctx)
        
        assert result.status == NodeStatus.FAILED
        assert result.error == "Command failed"


def test_bash_captures_stdout_and_stderr(bash_node):
    """Test stdout and stderr are both captured."""
    ctx = RunnerContext(node_def=bash_node)
    
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Standard output"
    mock_result.stderr = "Standard error"
    
    with patch("subprocess.run", return_value=mock_result):
        runner = BashRunner()
        result = runner.run(ctx)
        
        assert result.status == NodeStatus.COMPLETED
        assert result.output["stdout"] == "Standard output"
        assert result.output["stderr"] == "Standard error"

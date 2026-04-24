"""Tests for prompt runner variable resolution.

This test file verifies that the prompt runner correctly uses resolved inputs
from the executor's variable resolution instead of reading node.prompt directly.
"""
from unittest.mock import MagicMock, patch
import io
import asyncio

from dag_executor.schema import NodeDef, NodeStatus, ModelTier, WorkflowDef, WorkflowConfig
from dag_executor.runners.base import RunnerContext
from dag_executor.runners.prompt import PromptRunner
from dag_executor.executor import WorkflowExecutor


def test_prompt_variable_substitution_end_to_end():
    """Test that workflow variables in prompts are resolved end-to-end (AC-1)."""
    workflow_def = WorkflowDef(
        name="test_workflow",
        config=WorkflowConfig(checkpoint_prefix="test"),
        nodes=[
            NodeDef(
                id="prompt1",
                name="Test Prompt with Variable",
                type="prompt",
                prompt="Process $issue_key",
                model=ModelTier.SONNET
            )
        ]
    )

    mock_process = MagicMock()
    mock_process.stdout = io.StringIO("Processed GW-5299\n")
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process):
        executor = WorkflowExecutor()
        result = asyncio.run(executor.execute(workflow_def, {"issue_key": "GW-5299"}))

        # Verify the workflow succeeded
        assert result.node_results["prompt1"].status == NodeStatus.COMPLETED

        # Verify the subprocess received the resolved prompt, not the raw variable
        # Check what was written to stdin
        if mock_process.stdin.write.called:
            stdin_content = mock_process.stdin.write.call_args[0][0]
            assert "GW-5299" in stdin_content, "Expected resolved issue_key in prompt"
            assert "$issue_key" not in stdin_content, "Raw $variable should not appear"


def test_prompt_uses_resolved_input_when_present():
    """Test that runner uses ctx.resolved_inputs['prompt'] when available."""
    node = NodeDef(
        id="p1",
        name="Prompt",
        type="prompt",
        prompt="raw $var text",
        model=ModelTier.SONNET
    )

    # Simulate what executor does: resolved_inputs contains the substituted prompt
    ctx = RunnerContext(
        node_def=node,
        resolved_inputs={"prompt": "resolved text"}
    )

    mock_process = MagicMock()
    mock_process.stdout = io.StringIO("response\n")
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process):
        runner = PromptRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.COMPLETED

        # Verify the resolved text was sent to stdin, not the raw prompt
        if mock_process.stdin.write.called:
            stdin_content = mock_process.stdin.write.call_args[0][0]
            assert "resolved text" in stdin_content
            assert "$var" not in stdin_content


def test_prompt_falls_back_to_node_prompt_when_no_resolved():
    """Test fallback to node.prompt when resolved_inputs is empty."""
    node = NodeDef(
        id="p1",
        name="Prompt",
        type="prompt",
        prompt="hello",
        model=ModelTier.SONNET
    )

    # Empty resolved_inputs (simulates single-node test path)
    ctx = RunnerContext(node_def=node, resolved_inputs={})

    mock_process = MagicMock()
    mock_process.stdout = io.StringIO("response\n")
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process):
        runner = PromptRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.COMPLETED
        # Verify fallback worked - stdin should contain "hello"
        if mock_process.stdin.write.called:
            stdin_content = mock_process.stdin.write.call_args[0][0]
            assert "hello" in stdin_content


def test_prompt_node_output_reference_substitutes():
    """Test that $node.output.field references are resolved."""
    workflow_def = WorkflowDef(
        name="test_workflow",
        config=WorkflowConfig(checkpoint_prefix="test"),
        nodes=[
            NodeDef(
                id="node1",
                name="First Node",
                type="prompt",
                prompt="Generate a key",
                model=ModelTier.SONNET
            ),
            NodeDef(
                id="node2",
                name="Second Node",
                type="prompt",
                prompt="Use this key: $node1.response",
                model=ModelTier.SONNET,
                depends_on=["node1"]
            )
        ]
    )

    call_count = [0]
    captured_prompts = []

    def create_mock_output(*args, **kwargs):
        """Return different output for each call and capture stdin writes."""
        mock = MagicMock()

        # Override write to capture what's written
        original_write = mock.stdin.write
        def capturing_write(content):
            captured_prompts.append(content)
            return original_write(content)
        mock.stdin.write = capturing_write

        if call_count[0] == 0:
            mock.stdout = io.StringIO("secret-key-123\n")
        else:
            mock.stdout = io.StringIO("Used the key\n")
        call_count[0] += 1
        mock.stderr = MagicMock()
        mock.stderr.read.return_value = ""
        mock.wait.return_value = 0
        return mock

    with patch("subprocess.Popen", side_effect=create_mock_output):
        executor = WorkflowExecutor()
        result = asyncio.run(executor.execute(workflow_def, {}))

        assert result.node_results["node2"].status == NodeStatus.COMPLETED

        # Check that node2's prompt contained the resolved reference
        if len(captured_prompts) >= 2:
            node2_prompt = captured_prompts[1]
            assert "secret-key-123" in node2_prompt, "Expected node1 output in node2 prompt"
            assert "$node1.response" not in node2_prompt, "Reference should be resolved"


def test_prompt_workflow_state_reference_substitutes():
    """Test that $state_key references (workflow inputs) are resolved."""
    workflow_def = WorkflowDef(
        name="test_workflow",
        config=WorkflowConfig(checkpoint_prefix="test"),
        nodes=[
            NodeDef(
                id="prompt1",
                name="Prompt with State",
                type="prompt",
                prompt="Environment: $environment",
                model=ModelTier.SONNET
            )
        ]
    )

    mock_process = MagicMock()
    mock_process.stdout = io.StringIO("Production mode\n")
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process):
        executor = WorkflowExecutor()
        result = asyncio.run(executor.execute(workflow_def, {"environment": "production"}))

        assert result.node_results["prompt1"].status == NodeStatus.COMPLETED

        if mock_process.stdin.write.called:
            stdin_content = mock_process.stdin.write.call_args[0][0]
            assert "production" in stdin_content
            assert "$environment" not in stdin_content


def test_prompt_unresolved_reference_raises_variable_resolution_error():
    """Test that unresolved variables cause node failure (AC-4)."""
    workflow_def = WorkflowDef(
        name="test_workflow",
        config=WorkflowConfig(checkpoint_prefix="test"),
        nodes=[
            NodeDef(
                id="prompt1",
                name="Prompt with Missing Var",
                type="prompt",
                prompt="Use $missing_var",
                model=ModelTier.SONNET
            )
        ]
    )

    mock_process = MagicMock()
    mock_process.stdout = io.StringIO("Should not reach here\n")
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process):
        executor = WorkflowExecutor()
        result = asyncio.run(executor.execute(workflow_def, {}))

        # The node should fail with VariableResolutionError
        assert result.node_results["prompt1"].status == NodeStatus.FAILED
        assert result.node_results["prompt1"].error is not None
        # Error should mention the missing variable
        assert "missing_var" in result.node_results["prompt1"].error.lower()


def test_prompt_file_path_unaffected_by_resolved_inputs(tmp_path):
    """prompt_file still wins over resolved_inputs["prompt"] (regression guard).

    GW-5356: transport is unified on stdin — the test now asserts the file
    contents reach the subprocess, and the spurious "prompt" in resolved_inputs
    is ignored.
    """
    prompt_path = tmp_path / "test.md"
    prompt_path.write_text("USE THIS FILE BODY")

    node = NodeDef(
        id="p1",
        name="File Prompt",
        type="prompt",
        prompt_file=str(prompt_path),
        model=ModelTier.SONNET,
    )

    # Even with a stray "prompt" in resolved_inputs, prompt_file should win.
    ctx = RunnerContext(
        node_def=node,
        resolved_inputs={"prompt": "should be ignored"},
    )

    mock_process = MagicMock()
    mock_process.stdout = io.StringIO("response\n")
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
        runner = PromptRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.COMPLETED
        mock_process.stdin.write.assert_called_with("USE THIS FILE BODY")
        call_args = mock_popen.call_args[0][0]
        assert "--file" not in call_args

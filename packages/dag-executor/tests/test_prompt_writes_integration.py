"""Integration tests for prompt node writes with output_format."""
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch
import io

from dag_executor.executor import WorkflowExecutor
from dag_executor.parser import load_workflow
from dag_executor.schema import WorkflowStatus, NodeStatus


def test_prompt_output_format_json_spreads_fields():
    """Integration test: prompt with output_format=json spreads parsed fields to node output and writes."""
    fixture_path = Path(__file__).parent / "fixtures" / "prompt_writes_json.yaml"
    workflow_def = load_workflow(str(fixture_path))

    # Mock the subprocess to return JSON
    json_output = '{"result": "success", "count": 42}\n'
    mock_process = MagicMock()
    mock_process.stdout = io.StringIO(json_output)
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process):
        executor = WorkflowExecutor()
        result = asyncio.run(executor.execute(workflow_def, {}))

        # Workflow should complete successfully
        assert result.status == WorkflowStatus.COMPLETED
        assert result.node_results["prompt1"].status == NodeStatus.COMPLETED

        # Node output should contain parsed fields
        output = result.node_results["prompt1"].output
        assert output["result"] == "success"
        assert output["count"] == 42
        # Raw text should still be in response
        assert output["response"] == json_output

        # State channel should be populated with the parsed field value (not full text)
        assert result.outputs["result"] == "success"


def test_prompt_output_format_text_with_writes():
    """Integration test: prompt with output_format=text and writes:[result] populates both response and result."""
    fixture_path = Path(__file__).parent / "fixtures" / "prompt_writes_text.yaml"
    workflow_def = load_workflow(str(fixture_path))

    # Mock the subprocess to return text
    response_text = "The answer is 4\n"
    mock_process = MagicMock()
    mock_process.stdout = io.StringIO(response_text)
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process):
        executor = WorkflowExecutor()
        result = asyncio.run(executor.execute(workflow_def, {}))

        # Workflow should complete successfully
        assert result.status == WorkflowStatus.COMPLETED
        assert result.node_results["prompt1"].status == NodeStatus.COMPLETED

        # Node output should contain response and result (from writes)
        output = result.node_results["prompt1"].output
        assert output["response"] == response_text
        assert output["result"] == response_text

        # State channel should be populated via writes
        assert result.outputs["result"] == response_text


def test_prompt_output_format_text_without_writes():
    """Integration test: prompt with output_format=text and no writes produces only response key."""
    fixture_path = Path(__file__).parent / "fixtures" / "prompt_no_writes.yaml"
    workflow_def = load_workflow(str(fixture_path))

    # Mock the subprocess to return text
    response_text = "The answer is 4\n"
    mock_process = MagicMock()
    mock_process.stdout = io.StringIO(response_text)
    mock_process.stderr = MagicMock()
    mock_process.stderr.read.return_value = ""
    mock_process.stdin = MagicMock()
    mock_process.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_process):
        executor = WorkflowExecutor()
        result = asyncio.run(executor.execute(workflow_def, {}))

        # Workflow should complete successfully
        assert result.status == WorkflowStatus.COMPLETED
        assert result.node_results["prompt1"].status == NodeStatus.COMPLETED

        # Node output should only contain response key (no writes)
        output = result.node_results["prompt1"].output
        assert output == {"response": response_text}

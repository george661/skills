"""Integration tests for prompt node writes with output_format."""
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch
import io

from dag_executor.executor import WorkflowExecutor
from dag_executor.parser import load_workflow
from dag_executor.schema import WorkflowStatus, NodeStatus


def test_prompt_output_format_json_spreads_fields():
    """Integration test: prompt with output_format=json spreads parsed fields to node output."""
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


def test_prompt_output_format_text_only_response():
    """Integration test: prompt with output_format=text produces only response key."""
    fixture_path = Path(__file__).parent / "fixtures" / "prompt_writes_text.yaml"
    workflow_def = load_workflow(str(fixture_path))

    # Mock the subprocess to return text
    mock_process = MagicMock()
    mock_process.stdout = io.StringIO("The answer is 4\n")
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
        
        # Node output should only contain response key
        output = result.node_results["prompt1"].output
        assert output == {"response": "The answer is 4\n"}

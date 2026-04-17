"""Integration test for implement.yaml with channel state flow.

Mock-execution test: runs workflow with mock runners, verifies channel state
flows correctly between nodes, verifies state_diff in NODE_COMPLETED events,
and tests checkpoint resume with channels.
"""
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from dag_executor.executor import WorkflowExecutor
from dag_executor.parser import load_workflow


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "implement.yaml"
)


@pytest.fixture
def workflow():
    """Load implement.yaml workflow."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def mock_env():
    """Mock environment variables."""
    return {
        "PROJECT_ROOT": "/tmp/test",
        "TENANT_NAMESPACE": "test-tenant",
        "issue_key": "GW-1234",
        "E2E_REPO": "",  # No E2E for this test
    }


class MockRunner:
    """Mock runner that returns predefined outputs."""

    def __init__(self, outputs: Dict[str, Any]):
        self.outputs = outputs

    def run(self, node_id: str, **kwargs) -> Dict[str, Any]:
        """Return mock output for node."""
        return self.outputs.get(node_id, {})


class TestChannelStateFlow:
    """Test channel state flows correctly between nodes."""

    @patch("dag_executor.executor.BashRunner")
    @patch("dag_executor.executor.PromptRunner")
    def test_channel_writes_flow_to_downstream_reads(
        self, mock_prompt_runner, mock_bash_runner, workflow, mock_env
    ):
        """Channel data written by upstream nodes is available to downstream."""
        # Define mock outputs that write to channels
        mock_outputs = {
            "load_plan": {"plan": {"repo": "test-repo", "files": ["file1.py"]}},
            "plan_freshness": {"plan_status": "fresh"},
            "tdd_implement": {
                "impl_result": {"changed_files": ["file1.py"], "tests_passed": True}
            },
            "run_validation": {
                "validation_result": {"status": "passed"},
                "errors": [],
            },
            "file_location_guard": {},
            "push_and_create_pr": {
                "pr_info": {"repo": "test-repo", "pr_number": 42, "branch": "test-branch"}
            },
        }

        # Mock runner that returns channel data
        bash_instance = MagicMock()
        bash_instance.run.side_effect = lambda node, **kw: mock_outputs.get(node.id, {})
        mock_bash_runner.return_value = bash_instance

        prompt_instance = MagicMock()
        prompt_instance.run.side_effect = lambda node, **kw: mock_outputs.get(node.id, {})
        mock_prompt_runner.return_value = prompt_instance

        # Execute workflow
        executor = WorkflowExecutor(workflow)
        result = executor.execute(inputs=mock_env)

        # Verify channel state contains expected data
        assert result.channel_state.get("plan") is not None
        assert result.channel_state.get("plan_status") == "fresh"
        assert result.channel_state.get("impl_result") is not None
        assert result.channel_state.get("pr_info") is not None

    @patch("dag_executor.executor.emit_event")
    @patch("dag_executor.executor.BashRunner")
    def test_state_diff_in_node_completed_events(
        self, mock_bash_runner, mock_emit_event, workflow, mock_env
    ):
        """NODE_COMPLETED events include state_diff for nodes that write to channels."""
        mock_outputs = {
            "load_plan": {"plan": {"repo": "test-repo"}},
        }

        bash_instance = MagicMock()
        bash_instance.run.side_effect = lambda node, **kw: mock_outputs.get(node.id, {})
        mock_bash_runner.return_value = bash_instance

        executor = WorkflowExecutor(workflow)
        executor.execute(inputs=mock_env)

        # Find NODE_COMPLETED events
        completed_events = [
            call for call in mock_emit_event.call_args_list
            if call[0][0] == "NODE_COMPLETED"
        ]

        # Verify at least one event has state_diff
        assert len(completed_events) > 0
        # Check for state_diff in metadata
        for call in completed_events:
            event_data = call[0][1]
            if event_data.get("node_id") == "load_plan":
                assert "state_diff" in event_data.get("metadata", {})
                break


class TestCheckpointResumeWithChannels:
    """Test version-based checkpoint resume works with channels."""

    @patch("dag_executor.executor.BashRunner")
    def test_resume_skips_completed_nodes_with_channel_state(
        self, mock_bash_runner, workflow, mock_env
    ):
        """Interrupted workflow resumes from checkpoint with channel state intact."""
        # First run: execute partially
        mock_outputs = {
            "load_plan": {"plan": {"repo": "test-repo"}},
            "plan_freshness": {"plan_status": "fresh"},
        }

        bash_instance = MagicMock()
        bash_instance.run.side_effect = lambda node, **kw: mock_outputs.get(node.id, {})
        mock_bash_runner.return_value = bash_instance

        executor1 = WorkflowExecutor(workflow)
        # Simulate interrupt after plan_freshness
        with patch.object(executor1, "_should_interrupt", return_value=True):
            result1 = executor1.execute(inputs=mock_env)

        # Save checkpoint with channel state
        checkpoint_data = {
            "version": result1.version,
            "completed_nodes": list(result1.completed_nodes),
            "channel_state": result1.channel_state,
        }

        # Second run: resume from checkpoint
        executor2 = WorkflowExecutor(workflow)
        result2 = executor2.execute(
            inputs=mock_env,
            resume_from_checkpoint=checkpoint_data,
        )

        # Verify completed nodes were skipped
        assert "load_plan" not in result2.nodes_executed_this_run
        assert "plan_freshness" not in result2.nodes_executed_this_run
        # Verify channel state is restored
        assert result2.channel_state.get("plan") is not None
        assert result2.channel_state.get("plan_status") == "fresh"


class TestErrorAccumulation:
    """Test errors channel accumulates errors from multiple nodes."""

    @patch("dag_executor.executor.BashRunner")
    def test_errors_channel_appends(self, mock_bash_runner, workflow, mock_env):
        """Errors from validation and guard nodes accumulate in errors channel."""
        mock_outputs = {
            "load_plan": {"plan": {"repo": "test-repo"}},
            "plan_freshness": {"plan_status": "fresh"},
            "tdd_implement": {"impl_result": {}},
            "run_validation": {
                "validation_result": {"status": "failed"},
                "errors": ["Lint error"],
            },
            "file_location_guard": {
                "errors": ["File location violation"],
            },
        }

        bash_instance = MagicMock()
        bash_instance.run.side_effect = lambda node, **kw: mock_outputs.get(node.id, {})
        mock_bash_runner.return_value = bash_instance

        executor = WorkflowExecutor(workflow)
        result = executor.execute(inputs=mock_env)

        # Verify errors channel contains both errors
        errors = result.channel_state.get("errors", [])
        assert len(errors) == 2
        assert "Lint error" in errors
        assert "File location violation" in errors

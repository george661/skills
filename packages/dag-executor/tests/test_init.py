"""Tests for public API surface."""
import pytest
from dag_executor import (
    Node,
    NodeDef,
    NodeResult,
    NodeStatus,
    Workflow,
    WorkflowDef,
    WorkflowConfig,
    WorkflowStatus,
    WorkflowResult,
    execute_workflow,
    load_workflow,
    resume_workflow,
)


class TestPublicAPIExports:
    """Test that all expected public API functions and classes are exported."""
    
    def test_load_workflow_exists(self) -> None:
        """Verify load_workflow function is exported."""
        assert callable(load_workflow)
    
    def test_execute_workflow_exists(self) -> None:
        """Verify execute_workflow function is exported."""
        assert callable(execute_workflow)
    
    def test_resume_workflow_exists(self) -> None:
        """Verify resume_workflow function is exported."""
        assert callable(resume_workflow)
    
    def test_schema_classes_exported(self) -> None:
        """Verify schema classes are exported."""
        assert Workflow is not None
        assert Node is not None
        assert NodeStatus is not None
        assert WorkflowStatus is not None
        assert NodeResult is not None


class TestLoadWorkflow:
    """Test load_workflow public API."""

    def test_file_not_found(self) -> None:
        """Verify load_workflow raises FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError):
            load_workflow("/tmp/nonexistent_workflow.yaml")


class TestExecuteWorkflow:
    """Test execute_workflow behavior."""

    def test_executes_simple_workflow(self) -> None:
        """Verify execute_workflow executes a simple workflow successfully."""
        from unittest.mock import patch
        from dag_executor.runners.base import BaseRunner, RunnerContext

        node = NodeDef(id="node1", name="Test", type="bash", script="echo test")
        workflow_def = WorkflowDef(
            name="Test",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=[node]
        )

        # Mock the runner
        class MockRunner(BaseRunner):
            def run(self, ctx: RunnerContext) -> NodeResult:
                return NodeResult(status=NodeStatus.COMPLETED, output={"result": "ok"})

        with patch("dag_executor.executor.get_runner", return_value=MockRunner):
            result = execute_workflow(workflow_def, {})

        assert isinstance(result, WorkflowResult)
        assert result.status == WorkflowStatus.COMPLETED


class TestResumeWorkflow:
    """Test resume_workflow placeholder behavior."""

    def test_not_implemented(self) -> None:
        """Verify resume_workflow raises NotImplementedError."""
        node = NodeDef(id="node1", name="Test", type="bash", script="echo test")
        workflow_def = WorkflowDef(
            name="Test",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=[node]
        )

        # resume_workflow now requires checkpoint_store - test that it raises ValueError
        # when checkpoint is not found
        from dag_executor import CheckpointStore
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(str(Path(tmpdir) / ".checkpoints"))
            with pytest.raises(ValueError, match="No checkpoint found"):
                resume_workflow("Test", "nonexistent-run", store, workflow_def)


class TestResumeWorkflowWithCheckpointValues:
    """Test resume_workflow merges checkpoint-based resume values."""

    def test_run_resume_merges_checkpoint_values(self) -> None:
        """Verify resume_workflow loads and merges checkpoint resume values."""
        from unittest.mock import patch
        from dag_executor.runners.base import BaseRunner, RunnerContext
        from dag_executor import CheckpointStore, CheckpointMetadata
        from pathlib import Path
        import tempfile

        # Create a workflow with an interrupt node
        node = NodeDef(id="interrupt_node", name="Test Interrupt", type="interrupt",
                      message="Approval needed", resume_key="approval_status")
        workflow_def = WorkflowDef(
            name="TestWorkflow",
            config=WorkflowConfig(checkpoint_prefix=".checkpoints"),
            nodes=[node]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(str(Path(tmpdir) / ".checkpoints"))

            # Save checkpoint metadata
            metadata = CheckpointMetadata(
                workflow_name="TestWorkflow",
                run_id="run-123",
                started_at="2026-04-20T00:00:00Z",
                inputs={"original_input": "value"},
                status="interrupted"
            )
            store.save_metadata("TestWorkflow", "run-123", metadata)

            # Save resume values in checkpoint
            checkpoint_values = {"approval_status": "approved", "notes": "checkpoint"}
            store.save_resume_values("TestWorkflow", "run-123", checkpoint_values)

            # Mock the runner
            class MockRunner(BaseRunner):
                def run(self, ctx: RunnerContext) -> NodeResult:
                    # Verify that inputs contain merged resume values
                    return NodeResult(
                        status=NodeStatus.COMPLETED,
                        output={"merged_inputs": ctx.workflow_inputs}
                    )

            with patch("dag_executor.executor.get_runner", return_value=MockRunner):
                result = resume_workflow(
                    "TestWorkflow",
                    "run-123",
                    store,
                    workflow_def
                )

            # Checkpoint values should be merged
            assert result.status == WorkflowStatus.COMPLETED
            merged_inputs = result.node_results["interrupt_node"].output["merged_inputs"]
            assert merged_inputs["approval_status"] == "approved"
            assert merged_inputs["notes"] == "checkpoint"
            assert merged_inputs["original_input"] == "value"

    def test_run_resume_explicit_arg_wins_over_checkpoint(self) -> None:
        """Verify explicit resume_values argument takes precedence over checkpoint."""
        from unittest.mock import patch
        from dag_executor.runners.base import BaseRunner, RunnerContext
        from dag_executor import CheckpointStore, CheckpointMetadata
        from pathlib import Path
        import tempfile

        node = NodeDef(id="node1", name="Test", type="bash", script="echo test")
        workflow_def = WorkflowDef(
            name="TestWorkflow",
            config=WorkflowConfig(checkpoint_prefix=".checkpoints"),
            nodes=[node]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(str(Path(tmpdir) / ".checkpoints"))

            metadata = CheckpointMetadata(
                workflow_name="TestWorkflow",
                run_id="run-456",
                started_at="2026-04-20T00:00:00Z",
                inputs={},
                status="interrupted"
            )
            store.save_metadata("TestWorkflow", "run-456", metadata)

            # Save resume values in checkpoint
            store.save_resume_values("TestWorkflow", "run-456", {"key": "checkpoint_value"})

            class MockRunner(BaseRunner):
                def run(self, ctx: RunnerContext) -> NodeResult:
                    return NodeResult(
                        status=NodeStatus.COMPLETED,
                        output={"inputs": ctx.workflow_inputs}
                    )

            with patch("dag_executor.executor.get_runner", return_value=MockRunner):
                # Explicit arg should win
                result = resume_workflow(
                    "TestWorkflow",
                    "run-456",
                    store,
                    workflow_def,
                    resume_values={"key": "explicit_value"}
                )

            merged_inputs = result.node_results["node1"].output["inputs"]
            assert merged_inputs["key"] == "explicit_value"  # Explicit wins

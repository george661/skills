"""Tests for read_state filtering in validator and executor."""
import pytest
from unittest.mock import AsyncMock, patch
from dag_executor.schema import (
    NodeDef,
    NodeStatus,
    NodeResult,
    WorkflowDef,
    WorkflowConfig,
    InputDef,
    ReducerDef,
    ReducerStrategy,
)
from dag_executor.validator import WorkflowValidator
from dag_executor.executor import WorkflowExecutor


class TestReadStateValidation:
    """Test read_state validation in WorkflowValidator."""

    def test_read_state_with_workflow_inputs_passes(self):
        """Node with read_state referencing workflow inputs passes validation."""
        workflow = WorkflowDef(
            name="test-read-state-inputs",
            inputs={
                "repo": InputDef(type="string", required=True),
                "issue": InputDef(type="string", required=True),
            },
            nodes=[
                NodeDef(
                    id="node1",
                    type="bash",
                    name="Node1",
                    script="echo $repo $issue",
                    read_state=["repo", "issue"]
                ),
            ],
            config=WorkflowConfig(checkpoint_prefix="test"),
        )
        validator = WorkflowValidator()
        result = validator.validate(workflow)

        assert result.passed
        assert len([e for e in result.errors if e.code == "invalid_read_state_key"]) == 0

    def test_read_state_with_state_keys_passes(self):
        """Node with read_state referencing state reducer keys passes validation."""
        workflow = WorkflowDef(
            name="test-read-state-reducers",
            state={
                "results": ReducerDef(strategy=ReducerStrategy.APPEND),
                "errors": ReducerDef(strategy=ReducerStrategy.APPEND),
            },
            nodes=[
                NodeDef(
                    id="node1",
                    type="bash",
                    name="Node1",
                    script="echo test",
                    read_state=["results"]
                ),
            ],
            config=WorkflowConfig(checkpoint_prefix="test"),
        )
        validator = WorkflowValidator()
        result = validator.validate(workflow)

        assert result.passed

    def test_read_state_with_invalid_key_fails(self):
        """Node with read_state referencing non-existent key fails validation."""
        workflow = WorkflowDef(
            name="test-read-state-invalid",
            nodes=[
                NodeDef(
                    id="node1",
                    type="bash",
                    name="Node1",
                    script="echo test",
                    read_state=["nonexistent"]
                ),
            ],
            config=WorkflowConfig(checkpoint_prefix="test"),
        )
        validator = WorkflowValidator()
        result = validator.validate(workflow)

        assert not result.passed
        errors = [e for e in result.errors if e.code == "invalid_read_state_key"]
        assert len(errors) == 1
        assert "nonexistent" in errors[0].message


class TestReadStateExecutorFiltering:
    """Test read_state input filtering in WorkflowExecutor."""

    @pytest.mark.asyncio
    async def test_node_receives_only_declared_inputs(self):
        """Node with read_state receives only declared workflow inputs."""
        workflow = WorkflowDef(
            name="test-filtering",
            inputs={
                "key1": InputDef(type="string", required=False, default="value1"),
                "key2": InputDef(type="string", required=False, default="value2"),
                "key3": InputDef(type="string", required=False, default="value3"),
            },
            nodes=[
                NodeDef(
                    id="filtered-node",
                    type="bash",
                    name="FilteredNode",
                    script='echo "success"',
                    read_state=["key1", "key2"]
                ),
            ],
            config=WorkflowConfig(checkpoint_prefix="test"),
        )

        # Mock the runner to capture the actual workflow_inputs passed to it
        captured_ctx = []

        class MockRunner:
            def run(self, ctx):
                # Note: run is synchronous because it's called via run_in_executor
                captured_ctx.append(ctx)
                return NodeResult(
                    status=NodeStatus.COMPLETED,
                    output={"result": "success"}
                )

        executor = WorkflowExecutor()
        # get_runner returns a class, not an instance
        with patch("dag_executor.executor.get_runner", return_value=MockRunner):
            result = await executor.execute(
                workflow,
                inputs={"key1": "val1", "key2": "val2", "key3": "val3"}
            )

        # Verify the node succeeded
        assert result.status.value == "completed"
        assert "filtered-node" in result.node_results

        # Verify filtering: RunnerContext should only have key1 and key2, not key3
        assert len(captured_ctx) > 0, "Runner was not called"
        ctx = captured_ctx[0]
        assert "key1" in ctx.workflow_inputs
        assert "key2" in ctx.workflow_inputs
        assert "key3" not in ctx.workflow_inputs, "key3 should be filtered out"

    @pytest.mark.asyncio
    async def test_node_without_read_state_gets_full_state(self):
        """Node without read_state receives all workflow inputs (backward compat)."""
        workflow = WorkflowDef(
            name="test-no-filtering",
            inputs={
                "key1": InputDef(type="string", required=False, default="value1"),
                "key2": InputDef(type="string", required=False, default="value2"),
            },
            nodes=[
                NodeDef(
                    id="unfiltered-node",
                    type="bash",
                    name="UnfilteredNode",
                    script='echo "success"',
                    # No read_state declared - gets full state
                ),
            ],
            config=WorkflowConfig(checkpoint_prefix="test"),
        )

        executor = WorkflowExecutor()
        result = await executor.execute(
            workflow,
            inputs={"key1": "val1", "key2": "val2"}
        )

        assert result.status.value == "completed"
        # Node should succeed - backward compat preserved
        node_result = result.node_results["unfiltered-node"]
        assert node_result.status.value == "completed"

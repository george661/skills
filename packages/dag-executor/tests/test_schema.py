"""Tests for Pydantic schema models."""
from datetime import datetime

import pytest
from pydantic import ValidationError
from dag_executor.schema import (
    Node,
    NodeResult,
    NodeStatus,
    ReducerDef,
    ReducerStrategy,
    Workflow,
    WorkflowDef,
    WorkflowStatus,
)


class TestNodeStatus:
    """Test NodeStatus enum."""
    
    def test_enum_values(self) -> None:
        """Verify all expected enum values exist."""
        assert NodeStatus.PENDING == "pending"
        assert NodeStatus.RUNNING == "running"
        assert NodeStatus.COMPLETED == "completed"
        assert NodeStatus.FAILED == "failed"
        assert NodeStatus.SKIPPED == "skipped"
    
    def test_enum_membership(self) -> None:
        """Verify enum membership checks work."""
        assert "pending" in NodeStatus.__members__.values()
        assert "invalid" not in NodeStatus.__members__.values()


class TestWorkflowStatus:
    """Test WorkflowStatus enum."""
    
    def test_enum_values(self) -> None:
        """Verify all expected enum values exist."""
        assert WorkflowStatus.PENDING == "pending"
        assert WorkflowStatus.RUNNING == "running"
        assert WorkflowStatus.COMPLETED == "completed"
        assert WorkflowStatus.FAILED == "failed"
        assert WorkflowStatus.PAUSED == "paused"


class TestNodeResult:
    """Test NodeResult model."""
    
    def test_create_minimal(self) -> None:
        """Test creating NodeResult with minimal required fields."""
        result = NodeResult(status=NodeStatus.COMPLETED)
        assert result.status == NodeStatus.COMPLETED
        assert result.output is None
        assert result.error is None
        assert result.started_at is None
        assert result.completed_at is None
    
    def test_create_full(self) -> None:
        """Test creating NodeResult with all fields."""
        now = datetime.now()
        result = NodeResult(
            status=NodeStatus.COMPLETED,
            output={"result": "success"},
            error=None,
            started_at=now,
            completed_at=now,
        )
        assert result.status == NodeStatus.COMPLETED
        assert result.output == {"result": "success"}
        assert result.started_at == now
        assert result.completed_at == now
    
    def test_failed_with_error(self) -> None:
        """Test creating a failed NodeResult with error message."""
        result = NodeResult(
            status=NodeStatus.FAILED,
            error="Task execution failed"
        )
        assert result.status == NodeStatus.FAILED
        assert result.error == "Task execution failed"


class TestNode:
    """Test Node model."""
    
    def test_create_minimal(self) -> None:
        """Test creating Node with minimal required fields."""
        node = Node(id="node1", name="Test Node", runner="bash")
        assert node.id == "node1"
        assert node.name == "Test Node"
        assert node.runner == "bash"
        assert node.inputs == {}
        assert node.depends_on == []
        assert node.status == NodeStatus.PENDING
        assert node.result is None
    
    def test_create_with_dependencies(self) -> None:
        """Test creating Node with dependencies."""
        node = Node(
            id="node2",
            name="Dependent Node",
            runner="python",
            depends_on=["node1"],
            inputs={"arg1": "value1"}
        )
        assert node.depends_on == ["node1"]
        assert node.inputs == {"arg1": "value1"}
    
    def test_create_with_result(self) -> None:
        """Test creating Node with execution result."""
        result = NodeResult(status=NodeStatus.COMPLETED)
        node = Node(
            id="node3",
            name="Completed Node",
            runner="bash",
            status=NodeStatus.COMPLETED,
            result=result
        )
        assert node.status == NodeStatus.COMPLETED
        assert node.result is not None
        assert node.result.status == NodeStatus.COMPLETED


class TestWorkflow:
    """Test Workflow model."""
    
    def test_create_minimal(self) -> None:
        """Test creating Workflow with minimal required fields."""
        node = Node(id="node1", name="Test Node", runner="bash")
        workflow = Workflow(id="wf1", name="Test Workflow", nodes=[node])
        assert workflow.id == "wf1"
        assert workflow.name == "Test Workflow"
        assert len(workflow.nodes) == 1
        assert workflow.status == WorkflowStatus.PENDING
        assert workflow.metadata == {}
    
    def test_create_with_multiple_nodes(self) -> None:
        """Test creating Workflow with multiple nodes."""
        nodes = [
            Node(id="node1", name="First", runner="bash"),
            Node(id="node2", name="Second", runner="python", depends_on=["node1"]),
        ]
        workflow = Workflow(id="wf2", name="Multi-node Workflow", nodes=nodes)
        assert len(workflow.nodes) == 2
        assert workflow.nodes[1].depends_on == ["node1"]
    
    def test_create_with_metadata(self) -> None:
        """Test creating Workflow with metadata."""
        node = Node(id="node1", name="Test", runner="bash")
        workflow = Workflow(
            id="wf3",
            name="Workflow with Metadata",
            nodes=[node],
            metadata={"created_by": "test", "version": "1.0"}
        )
        assert workflow.metadata["created_by"] == "test"
        assert workflow.metadata["version"] == "1.0"
    
    def test_workflow_status_update(self) -> None:
        """Test updating workflow status."""
        node = Node(id="node1", name="Test", runner="bash")
        workflow = Workflow(
            id="wf4",
            name="Status Test",
            nodes=[node],
            status=WorkflowStatus.RUNNING
        )
        assert workflow.status == WorkflowStatus.RUNNING


class TestReducerStrategy:
    """Test ReducerStrategy enum."""

    def test_enum_values(self) -> None:
        """Verify all expected reducer strategy enum values exist."""
        assert ReducerStrategy.OVERWRITE == "overwrite"
        assert ReducerStrategy.APPEND == "append"
        assert ReducerStrategy.EXTEND == "extend"
        assert ReducerStrategy.MAX == "max"
        assert ReducerStrategy.MIN == "min"
        assert ReducerStrategy.MERGE_DICT == "merge_dict"
        assert ReducerStrategy.CUSTOM == "custom"


class TestReducerDef:
    """Test ReducerDef model."""

    def test_create_with_builtin_strategy(self) -> None:
        """Test creating ReducerDef with built-in strategy."""
        reducer = ReducerDef(strategy=ReducerStrategy.APPEND)
        assert reducer.strategy == ReducerStrategy.APPEND
        assert reducer.function is None

    def test_create_with_custom_strategy(self) -> None:
        """Test creating ReducerDef with custom strategy and function."""
        reducer = ReducerDef(
            strategy=ReducerStrategy.CUSTOM,
            function="mypackage.reducers.custom_merge"
        )
        assert reducer.strategy == ReducerStrategy.CUSTOM
        assert reducer.function == "mypackage.reducers.custom_merge"

    def test_custom_strategy_requires_function(self) -> None:
        """Test that custom strategy without function raises error."""
        with pytest.raises(ValidationError) as exc_info:
            ReducerDef(strategy=ReducerStrategy.CUSTOM)
        assert "function" in str(exc_info.value).lower()

    def test_builtin_strategy_rejects_function(self) -> None:
        """Test that built-in strategy with function raises error."""
        with pytest.raises(ValidationError) as exc_info:
            ReducerDef(
                strategy=ReducerStrategy.APPEND,
                function="mypackage.reducers.custom_merge"
            )
        assert "function" in str(exc_info.value).lower()

    def test_extra_fields_forbidden(self) -> None:
        """Test that extra fields are rejected."""
        with pytest.raises(ValidationError):
            ReducerDef(strategy=ReducerStrategy.APPEND, extra_field="not_allowed")  # type: ignore


class TestWorkflowDefWithState:
    """Test WorkflowDef with state reducers."""

    def test_workflow_def_without_state(self) -> None:
        """Test WorkflowDef backward compatibility (no state field)."""
        from dag_executor.schema import NodeDef, WorkflowConfig, ModelTier

        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=[
                NodeDef(
                    id="node1",
                    name="Test Node",
                    type="prompt",
                    prompt="test",
                    model=ModelTier.SONNET
                )
            ]
        )
        assert workflow_def.state == {}

    def test_workflow_def_with_state_reducers(self) -> None:
        """Test WorkflowDef with state reducer declarations."""
        from dag_executor.schema import NodeDef, WorkflowConfig, ModelTier

        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=[
                NodeDef(
                    id="node1",
                    name="Test Node",
                    type="prompt",
                    prompt="test",
                    model=ModelTier.SONNET
                )
            ],
            state={
                "findings": ReducerDef(strategy=ReducerStrategy.APPEND),
                "severity": ReducerDef(strategy=ReducerStrategy.MAX),
                "metadata": ReducerDef(strategy=ReducerStrategy.MERGE_DICT),
            }
        )
        assert "findings" in workflow_def.state
        assert workflow_def.state["findings"].strategy == ReducerStrategy.APPEND
        assert "severity" in workflow_def.state
        assert workflow_def.state["severity"].strategy == ReducerStrategy.MAX

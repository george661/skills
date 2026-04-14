"""Tests for Pydantic schema models."""
from datetime import datetime

import pytest
from dag_executor.schema import (
    Node,
    NodeResult,
    NodeStatus,
    Workflow,
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

"""Tests for public API surface."""
import pytest
from dag_executor import (
    Node,
    NodeResult,
    NodeStatus,
    Workflow,
    WorkflowStatus,
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
    """Test execute_workflow placeholder behavior."""
    
    def test_not_implemented(self) -> None:
        """Verify execute_workflow raises NotImplementedError."""
        node = Node(id="node1", name="Test", runner="bash")
        workflow = Workflow(id="wf1", name="Test", nodes=[node])
        
        with pytest.raises(NotImplementedError, match="execute_workflow not yet implemented"):
            execute_workflow(workflow)


class TestResumeWorkflow:
    """Test resume_workflow placeholder behavior."""
    
    def test_not_implemented(self) -> None:
        """Verify resume_workflow raises NotImplementedError."""
        node = Node(id="node1", name="Test", runner="bash")
        workflow = Workflow(id="wf1", name="Test", nodes=[node])
        
        with pytest.raises(NotImplementedError, match="resume_workflow not yet implemented"):
            resume_workflow(workflow)

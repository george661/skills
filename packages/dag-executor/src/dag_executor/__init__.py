"""DAG executor public API."""
from typing import Any, Dict, Optional

from dag_executor.schema import Workflow, Node, NodeStatus, WorkflowStatus, NodeResult

__all__ = [
    "load_workflow",
    "execute_workflow",
    "resume_workflow",
    "Workflow",
    "Node",
    "NodeStatus",
    "WorkflowStatus",
    "NodeResult",
]


def load_workflow(path: str) -> Workflow:
    """Load a workflow definition from a YAML file.
    
    Args:
        path: Path to workflow YAML file
        
    Returns:
        Parsed Workflow object
        
    Raises:
        FileNotFoundError: If the workflow file does not exist
        ValueError: If the workflow definition is invalid
    """
    raise NotImplementedError("load_workflow not yet implemented")


def execute_workflow(workflow: Workflow, context: Optional[Dict[str, Any]] = None) -> Workflow:
    """Execute a workflow from start to completion.
    
    Args:
        workflow: Workflow to execute
        context: Optional execution context variables
        
    Returns:
        Updated workflow with execution results
        
    Raises:
        RuntimeError: If workflow execution fails
    """
    raise NotImplementedError("execute_workflow not yet implemented")


def resume_workflow(workflow: Workflow, context: Optional[Dict[str, Any]] = None) -> Workflow:
    """Resume a paused or failed workflow from its last state.
    
    Args:
        workflow: Workflow to resume (must have existing state)
        context: Optional execution context variables
        
    Returns:
        Updated workflow with execution results
        
    Raises:
        ValueError: If workflow has no previous state to resume from
        RuntimeError: If workflow resumption fails
    """
    raise NotImplementedError("resume_workflow not yet implemented")


def main() -> None:
    """CLI entry point for dag-exec command."""
    import sys
    print("dag-exec CLI not yet implemented", file=sys.stderr)
    sys.exit(1)

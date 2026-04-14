"""DAG executor public API."""
import asyncio
from typing import Any, Dict, Optional

# Runtime models (execution tracking)
from dag_executor.schema import Workflow, Node, NodeStatus, WorkflowStatus, NodeResult

# Definition models (YAML parsing)
from dag_executor.schema import (
    WorkflowDef,
    NodeDef,
    WorkflowConfig,
    InputDef,
    OutputDef,
    TriggerRule,
    ModelTier,
    DispatchMode,
    OnFailure,
    OutputFormat,
    RetryConfig,
)

# Parser functions
from dag_executor.parser import load_workflow as _load_workflow_impl
from dag_executor.parser import load_workflow_from_string

# Graph algorithms
from dag_executor.graph import topological_sort_with_layers, CycleDetectedError

# Variable substitution
from dag_executor.variables import resolve_variables, VariableResolutionError

# Executor
from dag_executor.executor import WorkflowExecutor, WorkflowResult

# Events
from dag_executor.events import EventType, WorkflowEvent, EventEmitter

__all__ = [
    "load_workflow",
    "load_workflow_from_string",
    "execute_workflow",
    "resume_workflow",
    # Graph algorithms
    "topological_sort_with_layers",
    "CycleDetectedError",
    # Variable substitution
    "resolve_variables",
    "VariableResolutionError",
    # Executor
    "WorkflowExecutor",
    "WorkflowResult",
    # Events
    "EventType",
    "WorkflowEvent",
    "EventEmitter",
    # Runtime models
    "Workflow",
    "Node",
    "NodeStatus",
    "WorkflowStatus",
    "NodeResult",
    # Definition models
    "WorkflowDef",
    "NodeDef",
    "WorkflowConfig",
    "InputDef",
    "OutputDef",
    "TriggerRule",
    "ModelTier",
    "DispatchMode",
    "OnFailure",
    "OutputFormat",
    "RetryConfig",
]


def load_workflow(path: str) -> WorkflowDef:
    """Load a workflow definition from a YAML file.

    Args:
        path: Path to workflow YAML file

    Returns:
        Parsed WorkflowDef object

    Raises:
        FileNotFoundError: If the workflow file does not exist
        ValueError: If the workflow definition is invalid
    """
    return _load_workflow_impl(path)


def execute_workflow(
    workflow_def: WorkflowDef,
    inputs: Optional[Dict[str, Any]] = None,
    concurrency_limit: int = 10
) -> WorkflowResult:
    """Execute a workflow from start to completion.

    Args:
        workflow_def: Workflow definition to execute
        inputs: Workflow input values
        concurrency_limit: Maximum concurrent node executions

    Returns:
        WorkflowResult with execution status and node results

    Raises:
        RuntimeError: If workflow execution fails
    """
    executor = WorkflowExecutor()
    return asyncio.run(executor.execute(workflow_def, inputs or {}, concurrency_limit))


def resume_workflow(
    workflow_def: WorkflowDef,
    checkpoint: Dict[str, Any],
    inputs: Optional[Dict[str, Any]] = None,
    concurrency_limit: int = 10
) -> WorkflowResult:
    """Resume a paused or failed workflow from its last state.

    Args:
        workflow_def: Workflow definition to resume
        checkpoint: Saved execution state (node_results, node_outputs, etc.)
        inputs: Workflow input values
        concurrency_limit: Maximum concurrent node executions

    Returns:
        WorkflowResult with execution status and node results

    Raises:
        ValueError: If checkpoint is invalid
        RuntimeError: If workflow resumption fails
    """
    # TODO: Implement resume logic - load checkpoint, skip completed nodes
    raise NotImplementedError("resume_workflow not yet fully implemented")


def main() -> None:
    """CLI entry point for dag-exec command."""
    import sys
    print("dag-exec CLI not yet implemented", file=sys.stderr)
    sys.exit(1)

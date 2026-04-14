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

# Checkpoint store
from dag_executor.checkpoint import CheckpointStore, CheckpointMetadata, NodeCheckpoint

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
    # Checkpoint store
    "CheckpointStore",
    "CheckpointMetadata",
    "NodeCheckpoint",
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
    concurrency_limit: int = 10,
    checkpoint_store: Optional[CheckpointStore] = None,
    run_id: Optional[str] = None
) -> WorkflowResult:
    """Execute a workflow from start to completion.

    Args:
        workflow_def: Workflow definition to execute
        inputs: Workflow input values
        concurrency_limit: Maximum concurrent node executions
        checkpoint_store: Optional checkpoint store for state persistence
        run_id: Optional run identifier (generated if not provided)

    Returns:
        WorkflowResult with execution status and node results

    Raises:
        RuntimeError: If workflow execution fails
    """
    executor = WorkflowExecutor()
    return asyncio.run(
        executor.execute(workflow_def, inputs or {}, concurrency_limit, checkpoint_store, run_id)
    )


def resume_workflow(
    workflow_name: str,
    run_id: str,
    checkpoint_store: CheckpointStore,
    workflow_def: WorkflowDef,
    inputs: Optional[Dict[str, Any]] = None,
    concurrency_limit: int = 10
) -> WorkflowResult:
    """Resume a paused or failed workflow from its last state.

    Args:
        workflow_name: Name of the workflow
        run_id: Run identifier to resume
        checkpoint_store: Checkpoint store containing saved state
        workflow_def: Workflow definition to resume
        inputs: Workflow input values (from checkpoint metadata if not provided)
        concurrency_limit: Maximum concurrent node executions

    Returns:
        WorkflowResult with execution status and node results

    Raises:
        ValueError: If checkpoint is invalid or not found
        RuntimeError: If workflow resumption fails
    """
    # Load checkpoint metadata
    metadata = checkpoint_store.load_metadata(workflow_name, run_id)
    if not metadata:
        raise ValueError(f"No checkpoint found for workflow '{workflow_name}' run '{run_id}'")

    # Use checkpoint inputs if not explicitly provided
    if inputs is None:
        inputs = metadata.inputs

    # Load all completed node checkpoints
    node_checkpoints = checkpoint_store.load_all_nodes(workflow_name, run_id)

    # The executor will use checkpoint_store.check_cache() to skip completed nodes
    # by matching content hashes - completed nodes with matching hashes will be restored
    # from cache instead of re-executed
    executor = WorkflowExecutor()
    return asyncio.run(
        executor.execute(workflow_def, inputs, concurrency_limit, checkpoint_store, run_id)
    )


def main() -> None:
    """CLI entry point for dag-exec command."""
    import sys
    print("dag-exec CLI not yet implemented", file=sys.stderr)
    sys.exit(1)

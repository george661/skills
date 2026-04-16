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
    LabelsConfig,
    ExitHookDef,
    InputDef,
    OutputDef,
    ReducerDef,
    ReducerStrategy,
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
from dag_executor.executor import WorkflowExecutor, WorkflowResult, NodeSummary

# Events
from dag_executor.events import EventType, WorkflowEvent, EventEmitter, StreamMode

# Label management
from dag_executor.labels import LabelManager, LabelCallback

# Checkpoint store
from dag_executor.checkpoint import CheckpointStore, CheckpointMetadata, NodeCheckpoint, InterruptCheckpoint

# Validator
from dag_executor.validator import WorkflowValidator, ValidationResult, ValidationIssue

# Replay module
from dag_executor.replay import TraceRecorder, ExecutionTrace, TraceReplayer, ReplayIssue, TraceEvent

# Channels
from dag_executor.channels import (
    Channel,
    LastValueChannel,
    ReducerChannel,
    BarrierChannel,
    ChannelStore,
    ConflictError,
    ChannelConflictError,
)

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
    "NodeSummary",
    # Events
    "EventType",
    "WorkflowEvent",
    "EventEmitter",
    "StreamMode",
    # Label management
    "LabelManager",
    "LabelCallback",
    # Checkpoint store
    "CheckpointStore",
    "CheckpointMetadata",
    "NodeCheckpoint",
    "InterruptCheckpoint",
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
    "LabelsConfig",
    "ExitHookDef",
    "InputDef",
    "OutputDef",
    "ReducerDef",
    "ReducerStrategy",
    "TriggerRule",
    "ModelTier",
    "DispatchMode",
    "OnFailure",
    "OutputFormat",
    "RetryConfig",
    # Validator
    "WorkflowValidator",
    "ValidationResult",
    "ValidationIssue",
    # Replay module
    "TraceRecorder",
    "ExecutionTrace",
    "TraceReplayer",
    "ReplayIssue",
    "TraceEvent",
    # Channels
    "Channel",
    "LastValueChannel",
    "ReducerChannel",
    "BarrierChannel",
    "ChannelStore",
    "ConflictError",
    "ChannelConflictError",
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
    run_id: Optional[str] = None,
    event_emitter: Optional[EventEmitter] = None,
) -> WorkflowResult:
    """Execute a workflow from start to completion.

    Args:
        workflow_def: Workflow definition to execute
        inputs: Workflow input values
        concurrency_limit: Maximum concurrent node executions
        checkpoint_store: Optional checkpoint store for state persistence
        run_id: Optional run identifier (generated if not provided)
        event_emitter: Optional event emitter for streaming execution events

    Returns:
        WorkflowResult with execution status and node results

    Raises:
        RuntimeError: If workflow execution fails
    """
    executor = WorkflowExecutor()
    return asyncio.run(
        executor.execute(
            workflow_def, inputs or {}, concurrency_limit,
            event_emitter=event_emitter, checkpoint_store=checkpoint_store, run_id=run_id
        )
    )


def resume_workflow(
    workflow_name: str,
    run_id: str,
    checkpoint_store: CheckpointStore,
    workflow_def: WorkflowDef,
    inputs: Optional[Dict[str, Any]] = None,
    resume_values: Optional[Dict[str, Any]] = None,
    concurrency_limit: int = 10,
    event_emitter: Optional[EventEmitter] = None,
) -> WorkflowResult:
    """Resume a paused or failed workflow from its last state.

    Args:
        workflow_name: Name of the workflow
        run_id: Run identifier to resume
        checkpoint_store: Checkpoint store containing saved state
        workflow_def: Workflow definition to resume
        inputs: Workflow input values (from checkpoint metadata if not provided)
        resume_values: Values to inject for resume (keyed by resume_key from interrupt)
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
        inputs = metadata.inputs.copy()
    else:
        inputs = inputs.copy()

    # Load interrupt checkpoint if present
    interrupt_checkpoint = checkpoint_store.load_interrupt(workflow_name, run_id)
    if interrupt_checkpoint and resume_values:
        # Inject resume values into workflow inputs
        for resume_key, resume_value in resume_values.items():
            inputs[resume_key] = resume_value

    # The executor will use checkpoint_store.check_cache() to skip completed nodes
    # by matching content hashes - completed nodes with matching hashes will be restored
    # from cache instead of re-executed
    executor = WorkflowExecutor()
    return asyncio.run(
        executor.execute(
            workflow_def, inputs, concurrency_limit,
            event_emitter=event_emitter, checkpoint_store=checkpoint_store, run_id=run_id
        )
    )


def main() -> None:
    """CLI entry point for dag-exec command."""
    from dag_executor.cli import main as cli_main
    cli_main()

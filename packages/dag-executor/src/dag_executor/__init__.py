"""DAG executor public API."""
import asyncio
from pathlib import Path
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
    ChannelFieldDef,
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

# Terminal visualization
from dag_executor.terminal import ProgressBar, RunSummary, generate_mermaid

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
    "ChannelFieldDef",
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
    # Terminal visualization
    "ProgressBar",
    "RunSummary",
    "generate_mermaid",
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
    channel_store: Optional["ChannelStore"] = None,
    events_dir: Optional["Path"] = None,
    conversation_id: Optional[str] = None,
    db_path: Optional["Path"] = None,
) -> WorkflowResult:
    """Execute a workflow from start to completion.

    Args:
        workflow_def: Workflow definition to execute
        inputs: Workflow input values
        concurrency_limit: Maximum concurrent node executions
        checkpoint_store: Optional checkpoint store for state persistence
        run_id: Optional run identifier (generated if not provided)
        event_emitter: Optional event emitter for streaming execution events
        channel_store: Optional channel store for version-based checkpoint optimization
        events_dir: Optional directory for cancel marker files. When provided,
            the executor polls {events_dir}/{run_id}.cancel every 1s and
            triggers SIGTERM/SIGKILL on marker detection.
        conversation_id: Optional conversation ID for session continuity
        db_path: Optional path to dashboard database for conversation storage

    Returns:
        WorkflowResult with execution status and node results

    Raises:
        RuntimeError: If workflow execution fails
    """
    executor = WorkflowExecutor()
    return asyncio.run(
        executor.execute(
            workflow_def, inputs or {}, concurrency_limit,
            event_emitter=event_emitter, checkpoint_store=checkpoint_store, run_id=run_id,
            channel_store=channel_store, events_dir=events_dir,
            conversation_id=conversation_id, db_path=db_path,
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
    channel_store: Optional["ChannelStore"] = None,
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
        event_emitter: Optional event emitter for streaming execution events
        channel_store: Optional channel store for version-based checkpoint optimization

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

    # Load checkpoint-based resume values and merge into inputs
    checkpoint_resume_values = checkpoint_store.load_resume_values(workflow_name, run_id)
    if checkpoint_resume_values:
        for key, value in checkpoint_resume_values.items():
            inputs[key] = value

    # Explicit resume_values argument takes precedence over checkpoint values
    if resume_values:
        for resume_key, resume_value in resume_values.items():
            inputs[resume_key] = resume_value

    # The executor will use checkpoint_store.check_cache() to skip completed nodes
    # by matching content hashes - completed nodes with matching hashes will be restored
    # from cache instead of re-executed
    executor = WorkflowExecutor()
    return asyncio.run(
        executor.execute(
            workflow_def, inputs, concurrency_limit,
            event_emitter=event_emitter, checkpoint_store=checkpoint_store, run_id=run_id,
            channel_store=channel_store
        )
    )


def main() -> None:
    """CLI entry point for dag-exec command."""
    from dag_executor.cli import main as cli_main
    cli_main()

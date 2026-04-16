"""Core DAG workflow executor with layer-parallel execution."""
import asyncio
import copy
import json
import logging
import random
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

from simpleeval import SimpleEval  # type: ignore

from dag_executor.channels import ChannelStore
from dag_executor.graph import topological_sort_with_layers
from dag_executor.reducers import ReducerRegistry
from dag_executor.runners import get_runner
from dag_executor.runners.base import RunnerContext
from dag_executor.schema import (
    NodeDef, NodeResult, NodeStatus, OnFailure, TriggerRule,
    WorkflowDef, WorkflowStatus
)
from dag_executor.variables import resolve_variables

if TYPE_CHECKING:
    from dag_executor.events import EventEmitter
    from dag_executor.checkpoint import CheckpointStore, CheckpointMetadata


@dataclass
class NodeSummary:
    """Summary of node execution state for WorkflowResult.nodes."""
    id: str
    status: NodeStatus
    result: Optional[NodeResult] = None


@dataclass
class ExecutionContext:
    """Tracks execution state across the workflow.

    Attributes:
        node_outputs: Map of node_id -> output dict from completed nodes
        node_statuses: Map of node_id -> current NodeStatus
        node_results: Map of node_id -> full NodeResult
        workflow_inputs: Global workflow inputs
        workflow_state: Shared mutable state merged via reducers (backwards-compat view)
        channel_store: Channel-based state management (None = legacy dict mode)
        versions_seen: Per-node snapshot of channel versions at last execution
        _state_lock: Lock for thread-safe workflow_state mutations
        concurrency_limit: Max concurrent node executions
        stopped: Set to True when workflow should halt (on_failure=stop)
        interrupted: Set to True when workflow hits an interrupt node
        skipped_nodes: Set of node IDs marked for skipping
    """
    node_outputs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    node_statuses: Dict[str, NodeStatus] = field(default_factory=dict)
    node_results: Dict[str, NodeResult] = field(default_factory=dict)
    workflow_inputs: Dict[str, Any] = field(default_factory=dict)
    workflow_state: Dict[str, Any] = field(default_factory=dict)
    channel_store: Optional[ChannelStore] = field(default=None)
    versions_seen: Dict[str, Dict[str, int]] = field(default_factory=dict)
    _state_lock: threading.Lock = field(default_factory=threading.Lock)
    concurrency_limit: int = 10
    stopped: bool = False
    interrupted: bool = False
    skipped_nodes: Set[str] = field(default_factory=set)
    pool: Optional[ThreadPoolExecutor] = field(default=None, repr=False)
    semaphore: Optional[asyncio.Semaphore] = field(default=None, repr=False)


class WorkflowResult:
    """Result of workflow execution.

    Uses BaseModel-like structure for consistency with other schema models.
    """
    def __init__(
        self,
        status: WorkflowStatus,
        node_results: Dict[str, NodeResult],
        outputs: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        node_statuses: Optional[Dict[str, NodeStatus]] = None
    ):
        self.status = status
        self.node_results = node_results
        self.outputs = outputs or {}
        self.run_id = run_id or ""
        self._node_statuses = node_statuses or {}

    @property
    def nodes(self) -> List[NodeSummary]:
        """Convert node_results to list of typed node summaries."""
        node_list: List[NodeSummary] = []
        for node_id, result in self.node_results.items():
            node = NodeSummary(
                id=node_id,
                status=result.status,
                result=result
            )
            node_list.append(node)
        # Add nodes that don't have results yet (still pending)
        for node_id, status in self._node_statuses.items():
            if node_id not in self.node_results:
                node = NodeSummary(
                    id=node_id,
                    status=status,
                    result=None
                )
                node_list.append(node)
        return node_list


class WorkflowExecutor:
    """Executes workflow DAGs with layer-parallel node execution."""
    
    DEFAULT_TIMEOUTS = {
        "prompt": 300,
        "command": 300,
        "bash": 60,
        "skill": 60,
        "gate": 30,
    }
    
    async def execute(
        self,
        workflow_def: WorkflowDef,
        inputs: Dict[str, Any],
        concurrency_limit: int = 10,
        event_emitter: Optional["EventEmitter"] = None,
        checkpoint_store: Optional["CheckpointStore"] = None,
        run_id: Optional[str] = None
    ) -> WorkflowResult:
        """Execute workflow from start to completion.

        Args:
            workflow_def: Workflow definition to execute
            inputs: Workflow input values
            concurrency_limit: Maximum concurrent node executions
            event_emitter: Optional event emitter for workflow monitoring
            checkpoint_store: Optional checkpoint store for state persistence
            run_id: Optional run identifier (generated if not provided)

        Returns:
            WorkflowResult with execution status and node results
        """
        from dag_executor.events import EventType, WorkflowEvent

        # Generate run_id if not provided
        if run_id is None:
            run_id = str(uuid.uuid4())

        # Capture workflow start time once (reused in both event emission and checkpoint metadata)
        workflow_started_at = datetime.now(timezone.utc)
        started_at = workflow_started_at.isoformat()

        # Emit WORKFLOW_STARTED event
        if event_emitter:
            event_emitter.emit(WorkflowEvent(
                event_type=EventType.WORKFLOW_STARTED,
                workflow_id=workflow_def.name,
                status=WorkflowStatus.RUNNING,
                timestamp=workflow_started_at
            ))

        # Save initial checkpoint metadata if checkpoint_store provided
        if checkpoint_store:
            from dag_executor.checkpoint import CheckpointMetadata
            metadata = CheckpointMetadata(
                workflow_name=workflow_def.name,
                run_id=run_id,
                started_at=started_at,
                inputs=inputs,
                status="running"
            )
            checkpoint_store.save_metadata(workflow_def.name, run_id, metadata)

        # Initialize execution context with shared pool and semaphore
        pool = ThreadPoolExecutor(max_workers=concurrency_limit)
        ctx = ExecutionContext(
            workflow_inputs=inputs,
            concurrency_limit=concurrency_limit,
            pool=pool,
            semaphore=asyncio.Semaphore(concurrency_limit),
        )

        # Initialize all nodes to PENDING status
        for node in workflow_def.nodes:
            ctx.node_statuses[node.id] = NodeStatus.PENDING

        # Get topologically sorted layers
        layers = topological_sort_with_layers(workflow_def.nodes)

        # Build node map for quick lookup
        nodes_map = {node.id: node for node in workflow_def.nodes}

        # Execute layers sequentially, nodes within layer in parallel
        for layer in layers:
            if ctx.stopped:
                # Mark remaining nodes as skipped
                for node_id in layer:
                    if node_id not in ctx.node_results:
                        ctx.node_results[node_id] = NodeResult(
                            status=NodeStatus.SKIPPED,
                            error="Workflow stopped due to upstream failure"
                        )
                        ctx.node_statuses[node_id] = NodeStatus.SKIPPED
                        # Emit NODE_SKIPPED event
                        if event_emitter:
                            event_emitter.emit(WorkflowEvent(
                                event_type=EventType.NODE_SKIPPED,
                                workflow_id=workflow_def.name,
                                node_id=node_id,
                                status=NodeStatus.SKIPPED,
                                timestamp=datetime.now(timezone.utc)
                            ))
                continue

            if ctx.interrupted:
                # Skip remaining layers when interrupted
                break

            await self._execute_layer(
                layer, nodes_map, ctx, workflow_def, event_emitter, checkpoint_store, run_id
            )

            # Check if any node triggered a stop or interrupt
            if ctx.stopped or ctx.interrupted:
                break

        # Mark any remaining PENDING nodes as SKIPPED (when stopped or interrupted)
        if ctx.stopped or ctx.interrupted:
            for node_id, status in list(ctx.node_statuses.items()):
                if status == NodeStatus.PENDING:
                    error_msg = "Workflow interrupted" if ctx.interrupted else "Workflow stopped due to upstream failure"
                    ctx.node_results[node_id] = NodeResult(
                        status=NodeStatus.SKIPPED,
                        error=error_msg
                    )
                    ctx.node_statuses[node_id] = NodeStatus.SKIPPED
                    # Emit NODE_SKIPPED event
                    if event_emitter:
                        from dag_executor.events import EventType, WorkflowEvent
                        event_emitter.emit(WorkflowEvent(
                            event_type=EventType.NODE_SKIPPED,
                            workflow_id=workflow_def.name,
                            node_id=node_id,
                            status=NodeStatus.SKIPPED,
                            timestamp=datetime.now(timezone.utc)
                        ))

        # Shut down shared thread pool
        pool.shutdown(wait=False)

        # Compute final workflow status
        final_status = self._compute_workflow_status(ctx)

        # Extract workflow outputs
        outputs = self._extract_outputs(workflow_def, ctx)

        # Calculate workflow duration
        workflow_completed_at = datetime.now(timezone.utc)
        workflow_duration_ms = int((workflow_completed_at - workflow_started_at).total_seconds() * 1000)

        # Emit WORKFLOW_COMPLETED, WORKFLOW_FAILED, or WORKFLOW_INTERRUPTED event
        if event_emitter:
            if final_status == WorkflowStatus.PAUSED:
                event_emitter.emit(WorkflowEvent(
                    event_type=EventType.WORKFLOW_INTERRUPTED,
                    workflow_id=workflow_def.name,
                    status=final_status,
                    duration_ms=workflow_duration_ms,
                    timestamp=workflow_completed_at
                ))
            elif final_status == WorkflowStatus.COMPLETED:
                event_emitter.emit(WorkflowEvent(
                    event_type=EventType.WORKFLOW_COMPLETED,
                    workflow_id=workflow_def.name,
                    status=final_status,
                    duration_ms=workflow_duration_ms,
                    timestamp=workflow_completed_at
                ))
            else:
                event_emitter.emit(WorkflowEvent(
                    event_type=EventType.WORKFLOW_FAILED,
                    workflow_id=workflow_def.name,
                    status=final_status,
                    duration_ms=workflow_duration_ms,
                    timestamp=workflow_completed_at
                ))

        # Save final checkpoint metadata
        if checkpoint_store:
            from dag_executor.checkpoint import CheckpointMetadata
            final_metadata = CheckpointMetadata(
                workflow_name=workflow_def.name,
                run_id=run_id,
                started_at=started_at,
                inputs=inputs,
                status=final_status.value
            )
            checkpoint_store.save_metadata(workflow_def.name, run_id, final_metadata)

        # Execute exit hooks (guaranteed cleanup, like Argo exit hooks)
        if workflow_def.config.on_exit:
            await self._run_exit_hooks(
                workflow_def, final_status, ctx, event_emitter
            )

        return WorkflowResult(
            status=final_status,
            node_results=ctx.node_results,
            outputs=outputs,
            run_id=run_id,
            node_statuses=ctx.node_statuses
        )
    
    async def _execute_layer(
        self,
        layer_node_ids: List[str],
        nodes_map: Dict[str, NodeDef],
        ctx: ExecutionContext,
        workflow_def: WorkflowDef,
        event_emitter: Optional["EventEmitter"] = None,
        checkpoint_store: Optional["CheckpointStore"] = None,
        run_id: str = ""
    ) -> None:
        """Execute all nodes in a layer concurrently.

        Args:
            layer_node_ids: Node IDs in this layer
            nodes_map: Map of node_id -> NodeDef
            ctx: Execution context
            workflow_def: Workflow definition (for reducer application)
            event_emitter: Optional event emitter for workflow monitoring
            checkpoint_store: Optional checkpoint store
            run_id: Run identifier for checkpointing
        """
        # Create tasks for all nodes in layer
        tasks = []
        for node_id in layer_node_ids:
            node_def = nodes_map[node_id]
            task = self._execute_node(
                node_def, ctx, nodes_map, workflow_def, event_emitter, checkpoint_store, run_id
            )
            tasks.append(task)

        # Execute all nodes in parallel
        await asyncio.gather(*tasks)
    
    async def _execute_node(
        self,
        node_def: NodeDef,
        ctx: ExecutionContext,
        nodes_map: Dict[str, NodeDef],
        workflow_def: WorkflowDef,
        event_emitter: Optional["EventEmitter"] = None,
        checkpoint_store: Optional["CheckpointStore"] = None,
        run_id: str = ""
    ) -> None:
        """Execute a single node with all pre/post checks.

        Args:
            node_def: Node definition to execute
            ctx: Execution context
            nodes_map: Map of node_id -> NodeDef (for failure handling)
            workflow_def: Workflow definition (for reducer application)
            event_emitter: Optional event emitter for workflow monitoring
            checkpoint_store: Optional checkpoint store
            run_id: Run identifier for checkpointing
        """
        from dag_executor.events import EventType, WorkflowEvent

        node_id = node_def.id

        # Check if checkpointing is enabled for this node (respect node-level checkpoint flag)
        enable_checkpoint = checkpoint_store is not None and node_def.checkpoint is not False

        # Check cache for completed result (skip cache for interrupt nodes on resume)
        if enable_checkpoint and checkpoint_store:
            # Build dependency outputs for cache key
            dependency_outputs = {}
            for dep_id in node_def.depends_on:
                if dep_id in ctx.node_outputs:
                    dependency_outputs[dep_id] = ctx.node_outputs[dep_id]

            # Compute content hash and check cache
            content_hash = checkpoint_store.compute_content_hash(node_def, dependency_outputs)
            cached = checkpoint_store.check_cache(workflow_def.name, run_id, node_id, content_hash)

            # Don't restore INTERRUPTED status from cache (node needs to re-execute with resume value)
            if cached and cached.status == NodeStatus.COMPLETED:
                # Cache hit - restore result and skip execution
                result = NodeResult(
                    status=cached.status,
                    output=cached.output,
                    error=cached.error,
                    started_at=datetime.fromisoformat(cached.started_at),
                    completed_at=datetime.fromisoformat(cached.completed_at)
                )
                ctx.node_results[node_id] = result
                ctx.node_statuses[node_id] = result.status
                if result.output:
                    ctx.node_outputs[node_id] = result.output
                return

        # Check if already skipped
        if node_id in ctx.skipped_nodes:
            ctx.node_results[node_id] = NodeResult(
                status=NodeStatus.SKIPPED,
                error="Marked for skipping"
            )
            ctx.node_statuses[node_id] = NodeStatus.SKIPPED
            # Emit NODE_SKIPPED event
            if event_emitter:
                event_emitter.emit(WorkflowEvent(
                    event_type=EventType.NODE_SKIPPED,
                    workflow_id=workflow_def.name,
                    node_id=node_id,
                    status=NodeStatus.SKIPPED,
                    timestamp=datetime.now(timezone.utc)
                ))
            return

        # Evaluate when condition
        self._last_when_error: Optional[str] = None
        if not self._evaluate_when(node_def, ctx):
            error = self._last_when_error
            ctx.node_results[node_id] = NodeResult(
                status=NodeStatus.SKIPPED,
                error=error,
            )
            ctx.node_statuses[node_id] = NodeStatus.SKIPPED
            # Emit NODE_SKIPPED event
            if event_emitter:
                event_emitter.emit(WorkflowEvent(
                    event_type=EventType.NODE_SKIPPED,
                    workflow_id=workflow_def.name,
                    node_id=node_id,
                    status=NodeStatus.SKIPPED,
                    timestamp=datetime.now(timezone.utc)
                ))
            return

        # Check trigger rule
        if not self._check_trigger_rule(node_def, ctx):
            ctx.node_results[node_id] = NodeResult(
                status=NodeStatus.SKIPPED,
                error="Trigger rule not satisfied"
            )
            ctx.node_statuses[node_id] = NodeStatus.SKIPPED
            # Emit NODE_SKIPPED event
            if event_emitter:
                event_emitter.emit(WorkflowEvent(
                    event_type=EventType.NODE_SKIPPED,
                    workflow_id=workflow_def.name,
                    node_id=node_id,
                    status=NodeStatus.SKIPPED,
                    timestamp=datetime.now(timezone.utc)
                ))
            return

        # Mark as running
        ctx.node_statuses[node_id] = NodeStatus.RUNNING
        started_at = datetime.now(timezone.utc)

        # Emit NODE_STARTED event
        if event_emitter:
            event_emitter.emit(WorkflowEvent(
                event_type=EventType.NODE_STARTED,
                workflow_id=workflow_def.name,
                node_id=node_id,
                status=NodeStatus.RUNNING,
                model=node_def.model.value if node_def.model else None,
                dispatch=node_def.dispatch.value if node_def.dispatch else None,
                timestamp=started_at
            ))

        # Initialize pre_state for diff computation
        pre_state: Dict[str, Any] = {}

        try:
            # Resolve variables in node definition
            resolved_inputs = self._resolve_node_inputs(node_def, ctx)
            
            # Get runner
            runner_class = get_runner(node_def.type)
            if not runner_class:
                raise RuntimeError(f"No runner registered for node type: {node_def.type}")
            
            runner = runner_class()

            # Create progress callback that emits NODE_PROGRESS events
            progress_callback = None
            if event_emitter:
                def progress_callback(message: str, metadata: Dict[str, Any]) -> None:
                    from dag_executor.events import EventType, WorkflowEvent
                    event_emitter.emit(WorkflowEvent(
                        event_type=EventType.NODE_PROGRESS,
                        workflow_id=workflow_def.name,
                        node_id=node_def.id,
                        metadata={"message": message, **metadata},
                        timestamp=datetime.now(timezone.utc)
                    ))

            # Filter state based on read_state declaration
            if node_def.read_state is not None:
                # Filter workflow_inputs to only include declared keys
                filtered_workflow_inputs = {
                    k: v for k, v in ctx.workflow_inputs.items()
                    if k in node_def.read_state
                }
                # Filter node_outputs to only include outputs from nodes that produce read_state keys
                # For now, pass all node_outputs since we can't statically determine output keys
                filtered_node_outputs = ctx.node_outputs
            else:
                # No filtering - pass full state
                filtered_workflow_inputs = ctx.workflow_inputs
                filtered_node_outputs = ctx.node_outputs

            # Create runner context
            runner_ctx = RunnerContext(
                node_def=node_def,
                resolved_inputs=resolved_inputs,
                node_outputs=filtered_node_outputs,
                workflow_inputs=filtered_workflow_inputs,
                workflow_id=workflow_def.name,
                max_output_bytes=10 * 1024 * 1024,
                progress_callback=progress_callback,
                event_emitter=event_emitter
            )
            
            # Get timeout for this node
            timeout = self._get_node_timeout(node_def)

            # Capture pre-execution state snapshot for diff computation
            pre_state = copy.deepcopy(ctx.workflow_state)

            # Execute with retry logic (exponential backoff + jitter)
            result = await self._execute_with_retry(
                node_def, runner, runner_ctx, timeout, ctx, event_emitter
            )
        
        except Exception as e:
            result = NodeResult(
                status=NodeStatus.FAILED,
                error=str(e)
            )
        
        # Set timestamps
        completed_at = datetime.now(timezone.utc)
        result.started_at = started_at
        result.completed_at = completed_at

        # Calculate duration
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)

        # Check output size
        if result.output:
            output_size = len(json.dumps(result.output))
            if output_size > 10 * 1024 * 1024:
                # Truncate output
                result.output = {"_truncated": True, "_size_bytes": output_size}
                result.error = (result.error or "") + f" (Output truncated: {output_size} bytes)"

        # Store result
        ctx.node_results[node_id] = result
        ctx.node_statuses[node_id] = result.status

        # Store output for downstream variable resolution
        if result.status == NodeStatus.COMPLETED and result.output:
            # Parse JSON output if output_format=json is specified
            output_to_store = result.output
            if node_def.output_format == "json" and isinstance(result.output, dict):
                # BashRunner returns {"stdout": "...", "stderr": "..."}
                # When output_format=json, parse the JSON from stdout
                stdout = result.output.get("stdout", "")
                if stdout:
                    try:
                        parsed = json.loads(stdout.strip())
                        output_to_store = parsed
                    except (json.JSONDecodeError, ValueError):
                        # If parsing fails, keep the raw output
                        pass

            ctx.node_outputs[node_id] = output_to_store

            # Evaluate conditional edges to determine which branch to take
            if node_def.edges is not None:
                self._evaluate_edges(node_def, ctx)

            # Apply reducers to merge outputs into workflow_state
            if workflow_def.state and isinstance(output_to_store, dict):
                reducer_registry = ReducerRegistry()
                for output_key, output_value in output_to_store.items():
                    if output_key in workflow_def.state:
                        reducer_def = workflow_def.state[output_key]
                        # Thread-safe mutation of workflow_state
                        with ctx._state_lock:
                            current = ctx.workflow_state.get(output_key)
                            merged = reducer_registry.apply(
                                reducer_def.strategy,
                                current,
                                output_value,
                                custom_function=reducer_def.function
                            )
                            ctx.workflow_state[output_key] = merged

        # Compute state diff after reducer application
        state_diff: Dict[str, Any] = {}
        for key in ctx.workflow_state:
            if key not in pre_state or ctx.workflow_state[key] != pre_state.get(key):
                state_diff[key] = ctx.workflow_state[key]
        # Also check for keys that were in pre_state but removed (rare case)
        for key in pre_state:
            if key not in ctx.workflow_state:
                state_diff[key] = None

        # Handle INTERRUPTED status
        if result.status == NodeStatus.INTERRUPTED:
            # Set interrupted flag
            ctx.interrupted = True

            # Save interrupt checkpoint
            if checkpoint_store:
                from dag_executor.checkpoint import InterruptCheckpoint

                # Get pending nodes (not yet executed)
                pending_nodes = [
                    nid for nid, status in ctx.node_statuses.items()
                    if status == NodeStatus.PENDING
                ]

                interrupt_checkpoint = InterruptCheckpoint(
                    node_id=node_id,
                    message=result.output.get("message", "") if result.output else "",
                    resume_key=result.output.get("resume_key", "") if result.output else "",
                    channels=result.output.get("channels", ["terminal"]) if result.output else ["terminal"],
                    timeout=node_def.timeout,
                    workflow_state=ctx.workflow_state.copy(),
                    pending_nodes=pending_nodes
                )
                checkpoint_store.save_interrupt(workflow_def.name, run_id, interrupt_checkpoint)

            # Emit NODE_INTERRUPTED event
            if event_emitter:
                event_emitter.emit(WorkflowEvent(
                    event_type=EventType.NODE_INTERRUPTED,
                    workflow_id=workflow_def.name,
                    node_id=node_id,
                    status=NodeStatus.INTERRUPTED,
                    duration_ms=duration_ms,
                    metadata={
                        "message": result.output.get("message", "") if result.output else "",
                        "resume_key": result.output.get("resume_key", "") if result.output else "",
                        "channels": result.output.get("channels", ["terminal"]) if result.output else ["terminal"]
                    },
                    timestamp=completed_at
                ))
            return

        # Emit NODE_COMPLETED or NODE_FAILED event
        if event_emitter:
            if result.status == NodeStatus.COMPLETED:
                event_emitter.emit(WorkflowEvent(
                    event_type=EventType.NODE_COMPLETED,
                    workflow_id=workflow_def.name,
                    node_id=node_id,
                    status=NodeStatus.COMPLETED,
                    duration_ms=duration_ms,
                    model=node_def.model.value if node_def.model else None,
                    dispatch=node_def.dispatch.value if node_def.dispatch else None,
                    metadata={"state_diff": state_diff},
                    timestamp=completed_at
                ))
            elif result.status == NodeStatus.FAILED:
                event_emitter.emit(WorkflowEvent(
                    event_type=EventType.NODE_FAILED,
                    workflow_id=workflow_def.name,
                    node_id=node_id,
                    status=NodeStatus.FAILED,
                    duration_ms=duration_ms,
                    model=node_def.model.value if node_def.model else None,
                    dispatch=node_def.dispatch.value if node_def.dispatch else None,
                    metadata={"error": result.error} if result.error else {},
                    timestamp=completed_at
                ))

        # Save checkpoint after successful execution
        if enable_checkpoint and checkpoint_store and result.status == NodeStatus.COMPLETED:
            # Rebuild dependency outputs for hash computation
            dependency_outputs = {}
            for dep_id in node_def.depends_on:
                if dep_id in ctx.node_outputs:
                    dependency_outputs[dep_id] = ctx.node_outputs[dep_id]
            content_hash = checkpoint_store.compute_content_hash(node_def, dependency_outputs)
            checkpoint_store.save_node(workflow_def.name, run_id, node_id, result, content_hash)

        # Handle failure
        if result.status == NodeStatus.FAILED:
            await self._handle_failure(node_def, ctx, nodes_map)
    
    def _evaluate_when(
        self,
        node_def: NodeDef,
        ctx: ExecutionContext
    ) -> bool:
        """Evaluate when condition for a node.

        Args:
            node_def: Node definition
            ctx: Execution context

        Returns:
            True if node should execute, False to skip
        """
        if node_def.when is None:
            return True

        # Handle string literals
        when_expr = node_def.when.strip()
        if when_expr.lower() in ("true", "1"):
            return True
        if when_expr.lower() in ("false", "0", ""):
            return False

        # Prepare evaluation context with workflow inputs and node outputs
        eval_context = {**ctx.workflow_inputs}

        # Flatten node outputs into context
        for node_id, output in ctx.node_outputs.items():
            if isinstance(output, dict):
                for key, value in output.items():
                    eval_context[f"{node_id}.{key}"] = value
            else:
                eval_context[node_id] = output

        # Evaluate expression
        evaluator = SimpleEval(names=eval_context)
        try:
            result = evaluator.eval(when_expr)
            return bool(result)
        except Exception as e:
            # Store error context so callers can see why the node was skipped
            self._last_when_error = f"when condition '{when_expr}' failed: {e}"
            return False

    def _evaluate_edges(
        self,
        node_def: NodeDef,
        ctx: ExecutionContext
    ) -> None:
        """Evaluate conditional edges and mark non-matching branches for skipping.

        Args:
            node_def: Node definition with edges
            ctx: Execution context
        """
        from types import SimpleNamespace

        if node_def.edges is None:
            return

        # Prepare evaluation context with workflow inputs
        eval_context = {**ctx.workflow_inputs}

        # Add node outputs as objects for dot notation access
        for node_id, output in ctx.node_outputs.items():
            if isinstance(output, dict):
                # Convert dict to SimpleNamespace for dot access (e.g., review.verdict)
                eval_context[node_id] = SimpleNamespace(**output)
            else:
                eval_context[node_id] = output

        # Find first matching edge (first truthy condition wins)
        # matching_targets is a list to support multi-target fan-out
        matching_targets: Optional[List[str]] = None
        default_targets: Optional[List[str]] = None

        for edge in node_def.edges:
            if edge.default:
                # Store default edge as fallback (single or multi-target)
                default_targets = edge.targets if edge.targets else [edge.target] if edge.target else []
                continue

            # Evaluate condition
            if edge.condition:
                evaluator = SimpleEval(names=eval_context)
                try:
                    result = evaluator.eval(edge.condition)
                    if result:
                        # Match found - store targets (single or multi)
                        matching_targets = edge.targets if edge.targets else [edge.target] if edge.target else []
                        break  # First match wins
                except Exception:
                    # Condition evaluation failed, try next edge
                    continue

        # Use default if no condition matched
        if matching_targets is None and default_targets is not None:
            matching_targets = default_targets

        # Mark all non-matching edge targets for skipping
        if matching_targets:
            # Collect all possible targets from all edges
            all_edge_targets = set()
            for edge in node_def.edges:
                if edge.targets:
                    all_edge_targets.update(edge.targets)
                elif edge.target:
                    all_edge_targets.add(edge.target)

            # Skip targets that are not in the matching set
            for target in all_edge_targets:
                if target not in matching_targets:
                    ctx.skipped_nodes.add(target)

    def _check_trigger_rule(
        self,
        node_def: NodeDef,
        ctx: ExecutionContext
    ) -> bool:
        """Check if trigger rule is satisfied.
        
        Args:
            node_def: Node definition
            ctx: Execution context
        
        Returns:
            True if trigger rule satisfied, False to skip
        """
        if not node_def.depends_on:
            # No dependencies, always execute
            return True
        
        # Get upstream statuses
        upstream_statuses = [
            ctx.node_statuses.get(dep_id, NodeStatus.PENDING)
            for dep_id in node_def.depends_on
        ]
        
        # Apply trigger rule
        if node_def.trigger_rule == TriggerRule.ALL_SUCCESS:
            # All must be completed
            return all(status == NodeStatus.COMPLETED for status in upstream_statuses)
        
        elif node_def.trigger_rule == TriggerRule.ONE_SUCCESS:
            # At least one must be completed
            return any(status == NodeStatus.COMPLETED for status in upstream_statuses)
        
        elif node_def.trigger_rule == TriggerRule.ALL_DONE:
            # All must be in terminal state
            terminal_states = {NodeStatus.COMPLETED, NodeStatus.FAILED, NodeStatus.SKIPPED}
            return all(status in terminal_states for status in upstream_statuses)
        
        return True
    
    def _resolve_node_inputs(
        self,
        node_def: NodeDef,
        ctx: ExecutionContext
    ) -> Dict[str, Any]:
        """Resolve variable references in node inputs.

        Args:
            node_def: Node definition
            ctx: Execution context

        Returns:
            Resolved inputs dict
        """
        # Collect all relevant fields to resolve
        inputs_to_resolve: Dict[str, Any] = {}

        # Add type-specific fields
        if node_def.script:
            inputs_to_resolve["script"] = node_def.script
        if node_def.command:
            inputs_to_resolve["command"] = node_def.command
        if node_def.args:
            inputs_to_resolve["args"] = node_def.args
        if node_def.params:
            inputs_to_resolve["params"] = node_def.params
        if node_def.prompt:
            inputs_to_resolve["prompt"] = node_def.prompt
        if node_def.condition:
            inputs_to_resolve["condition"] = node_def.condition

        # Resolve variables
        resolved = resolve_variables(
            inputs_to_resolve,
            ctx.node_outputs,
            ctx.workflow_inputs
        )

        return resolved  # type: ignore[no-any-return]
    
    async def _handle_failure(
        self,
        node_def: NodeDef,
        ctx: ExecutionContext,
        nodes_map: Dict[str, NodeDef]
    ) -> None:
        """Handle node failure according to on_failure policy.
        
        Args:
            node_def: Failed node definition
            ctx: Execution context
            nodes_map: Map of node_id -> NodeDef
        """
        if node_def.on_failure == OnFailure.STOP:
            # Stop workflow execution
            ctx.stopped = True
        
        elif node_def.on_failure == OnFailure.CONTINUE:
            # Do nothing, execution continues
            pass
        
        elif node_def.on_failure == OnFailure.SKIP_DOWNSTREAM:
            # Mark all downstream nodes as skipped
            self._mark_downstream_skipped(node_def.id, nodes_map, ctx)
    
    def _mark_downstream_skipped(
        self,
        failed_node_id: str,
        nodes_map: Dict[str, NodeDef],
        ctx: ExecutionContext
    ) -> None:
        """Recursively mark all downstream nodes as skipped.
        
        Args:
            failed_node_id: ID of the failed node
            nodes_map: Map of node_id -> NodeDef
            ctx: Execution context
        """
        # Find all nodes that depend on this node
        for node_id, node_def in nodes_map.items():
            if failed_node_id in node_def.depends_on:
                ctx.skipped_nodes.add(node_id)
                # Recursively mark its dependents
                self._mark_downstream_skipped(node_id, nodes_map, ctx)
    
    async def _run_exit_hooks(
        self,
        workflow_def: WorkflowDef,
        final_status: WorkflowStatus,
        ctx: ExecutionContext,
        event_emitter: Optional["EventEmitter"] = None,
    ) -> None:
        """Execute exit hooks that match the final workflow status.

        Exit hooks run sequentially, never fail the workflow (errors are logged),
        and have access to workflow_state for context (e.g., worktree path, PR number).

        Args:
            workflow_def: Workflow definition with on_exit hooks
            final_status: Final workflow status (completed, failed, paused)
            ctx: Execution context (for workflow_state access)
            event_emitter: Optional event emitter
        """
        from dag_executor.events import EventType, WorkflowEvent
        from dag_executor.runners.base import RunnerContext

        for hook in workflow_def.config.on_exit:
            # Check if this hook should run for the current status
            if final_status.value not in hook.run_on:
                continue

            # Build a synthetic NodeDef for the runner
            hook_node = NodeDef(
                id=f"_exit_{hook.id}",
                name=hook.name or f"Exit: {hook.id}",
                type=hook.type,
                script=hook.script,
                skill=hook.skill,
                params=hook.params,
                timeout=hook.timeout,
            )

            try:
                runner_class = get_runner(hook.type)
                if not runner_class:
                    continue

                runner = runner_class()
                # Merge workflow_state into workflow_inputs under "workflow_state" key
                # to provide exit hooks access to state (e.g., worktree_path, pr_number)
                exit_hook_inputs = {
                    **ctx.workflow_inputs,
                    "workflow_state": ctx.workflow_state,
                }
                runner_ctx = RunnerContext(
                    node_def=hook_node,
                    resolved_inputs={},
                    node_outputs=ctx.node_outputs,
                    workflow_inputs=exit_hook_inputs,
                    workflow_id=workflow_def.name,
                )

                # Run with timeout in the thread pool
                loop = asyncio.get_running_loop()
                pool = ThreadPoolExecutor(max_workers=1)
                try:
                    await asyncio.wait_for(
                        loop.run_in_executor(pool, runner.run, runner_ctx),
                        timeout=float(hook.timeout),
                    )
                finally:
                    pool.shutdown(wait=False)

                if event_emitter:
                    event_emitter.emit(WorkflowEvent(
                        event_type=EventType.NODE_COMPLETED,
                        workflow_id=workflow_def.name,
                        node_id=hook_node.id,
                        status=NodeStatus.COMPLETED,
                        timestamp=datetime.now(timezone.utc),
                    ))

            except Exception:
                # Exit hooks must never crash the workflow — log and continue
                if event_emitter:
                    event_emitter.emit(WorkflowEvent(
                        event_type=EventType.NODE_FAILED,
                        workflow_id=workflow_def.name,
                        node_id=f"_exit_{hook.id}",
                        status=NodeStatus.FAILED,
                        timestamp=datetime.now(timezone.utc),
                    ))

    async def _execute_with_retry(
        self,
        node_def: NodeDef,
        runner: Any,
        runner_ctx: Any,
        timeout: float,
        ctx: ExecutionContext,
        event_emitter: Optional["EventEmitter"] = None,
    ) -> NodeResult:
        """Execute a runner with retry logic using exponential backoff + jitter.

        If node_def.retry is None, executes once (no retry).
        Otherwise retries up to max_attempts with exponential backoff.

        Backoff formula: min(delay_ms * 2^attempt + jitter, 30000) ms
        Jitter: random 0-25% of computed delay

        Args:
            node_def: Node definition (contains retry config)
            runner: Instantiated runner
            runner_ctx: Runner context
            timeout: Per-attempt timeout in seconds
            ctx: Execution context (for pool/semaphore)
            event_emitter: Optional event emitter for retry progress

        Returns:
            NodeResult from final attempt
        """
        from dag_executor.events import EventType, WorkflowEvent

        max_attempts = 1
        base_delay_ms = 0
        retry_on_patterns: Optional[List[str]] = None
        if node_def.retry:
            max_attempts = node_def.retry.max_attempts
            base_delay_ms = node_def.retry.delay_ms
            retry_on_patterns = node_def.retry.retry_on

        last_result: Optional[NodeResult] = None
        loop = asyncio.get_running_loop()
        assert ctx.semaphore is not None
        assert ctx.pool is not None

        # Clear any partial outputs before retry loop starts (prevents state corruption)
        ctx.node_outputs.pop(node_def.id, None)

        for attempt in range(max_attempts):
            async with ctx.semaphore:
                try:
                    result: NodeResult = await asyncio.wait_for(
                        loop.run_in_executor(ctx.pool, runner.run, runner_ctx),
                        timeout=timeout
                    )
                except asyncio.TimeoutError:
                    result = NodeResult(
                        status=NodeStatus.FAILED,
                        error=f"Node execution timed out after {timeout}s"
                    )

            last_result = result

            # Success or non-retryable status — return immediately
            if result.status != NodeStatus.FAILED:
                return result

            # If retry_on filter is set, check if error matches any pattern
            if retry_on_patterns is not None and result.error:
                error_matches = any(
                    pattern.lower() in result.error.lower()
                    for pattern in retry_on_patterns
                )
                if not error_matches:
                    # Error doesn't match filter — don't retry, return immediately
                    break

            # Last attempt — don't sleep, just return the failure
            if attempt >= max_attempts - 1:
                break

            # Compute backoff delay: base * 2^attempt + jitter, capped at 30s
            delay_ms = base_delay_ms * (2 ** attempt) if base_delay_ms > 0 else 1000 * (2 ** attempt)
            jitter_ms = random.randint(0, max(1, int(delay_ms * 0.25)))
            actual_delay_ms = min(delay_ms + jitter_ms, 30_000)

            # Emit retry progress event
            if event_emitter:
                event_emitter.emit(WorkflowEvent(
                    event_type=EventType.NODE_PROGRESS,
                    workflow_id=runner_ctx.workflow_id,
                    node_id=node_def.id,
                    metadata={
                        "message": f"Retry {attempt + 1}/{max_attempts - 1}: "
                                   f"waiting {actual_delay_ms}ms before next attempt",
                        "attempt": attempt + 1,
                        "max_attempts": max_attempts,
                        "delay_ms": actual_delay_ms,
                        "last_error": result.error,
                    },
                    timestamp=datetime.now(timezone.utc),
                ))

            await asyncio.sleep(actual_delay_ms / 1000.0)

        assert last_result is not None
        return last_result

    def _get_node_timeout(self, node_def: NodeDef) -> float:
        """Get timeout for a node.
        
        Args:
            node_def: Node definition
        
        Returns:
            Timeout in seconds
        """
        if node_def.timeout:
            return float(node_def.timeout)
        
        # Use default based on node type
        return float(self.DEFAULT_TIMEOUTS.get(node_def.type, 60))
    
    def _compute_workflow_status(self, ctx: ExecutionContext) -> WorkflowStatus:
        """Compute final workflow status.

        Args:
            ctx: Execution context

        Returns:
            Final workflow status
        """
        statuses = ctx.node_statuses.values()

        # Check for interrupted nodes first (PAUSED takes priority)
        if any(status == NodeStatus.INTERRUPTED for status in statuses):
            return WorkflowStatus.PAUSED

        if any(status == NodeStatus.FAILED for status in statuses):
            return WorkflowStatus.FAILED

        if all(status in {NodeStatus.COMPLETED, NodeStatus.SKIPPED} for status in statuses):
            return WorkflowStatus.COMPLETED

        return WorkflowStatus.FAILED
    
    def _extract_outputs(
        self,
        workflow_def: WorkflowDef,
        ctx: ExecutionContext
    ) -> Dict[str, Any]:
        """Extract workflow outputs from node results and workflow state.

        Args:
            workflow_def: Workflow definition
            ctx: Execution context

        Returns:
            Workflow outputs dict
        """
        outputs = {}

        # First, extract outputs from workflow_state (reducer-merged values)
        # These have priority since they're the aggregated results
        outputs.update(ctx.workflow_state)

        # Then, extract node-specific outputs defined in workflow outputs
        for output_name, output_def in workflow_def.outputs.items():
            source_node = output_def.node
            if source_node in ctx.node_outputs:
                node_output = ctx.node_outputs[source_node]

                if output_def.field:
                    # Extract specific field
                    if isinstance(node_output, dict) and output_def.field in node_output:
                        outputs[output_name] = node_output[output_def.field]
                else:
                    # Use entire output
                    outputs[output_name] = node_output

        return outputs

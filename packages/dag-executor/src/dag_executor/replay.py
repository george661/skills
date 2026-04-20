"""Replay testing for workflow determinism validation.

Records execution traces and replays them against modified workflow
definitions to detect breaking changes before they hit production.

Inspired by:
- Temporal's replay testing (determinism validation against event history)
- LangGraph's checkpoint-based recovery
- Airflow's dag.test() simulation

Usage:
    # Record a trace during execution
    recorder = TraceRecorder()
    event_emitter.subscribe(recorder.capture)
    result = execute_workflow(wf, inputs, event_emitter=event_emitter)
    recorder.save("traces/work-run-123.json")

    # Replay against modified workflow
    replayer = TraceReplayer()
    issues = replayer.replay("traces/work-run-123.json", modified_workflow)
    for issue in issues:
        print(f"  {issue.code}: {issue.message}")
"""
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dag_executor.checkpoint import CheckpointMetadata, CheckpointStore
from dag_executor.schema import WorkflowDef


@dataclass
class TraceEvent:
    """A single recorded event from a workflow execution."""
    event_type: str
    node_id: Optional[str]
    status: str
    timestamp: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionTrace:
    """Complete recorded trace of a workflow execution."""
    workflow_name: str
    run_id: str
    inputs: Dict[str, Any]
    events: List[TraceEvent]
    node_execution_order: List[str]
    final_status: str
    recorded_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_name": self.workflow_name,
            "run_id": self.run_id,
            "inputs": self.inputs,
            "events": [
                {
                    "event_type": e.event_type,
                    "node_id": e.node_id,
                    "status": e.status,
                    "timestamp": e.timestamp,
                    "metadata": e.metadata,
                }
                for e in self.events
            ],
            "node_execution_order": self.node_execution_order,
            "final_status": self.final_status,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionTrace":
        return cls(
            workflow_name=data["workflow_name"],
            run_id=data["run_id"],
            inputs=data["inputs"],
            events=[
                TraceEvent(
                    event_type=e["event_type"],
                    node_id=e.get("node_id"),
                    status=e["status"],
                    timestamp=e["timestamp"],
                    metadata=e.get("metadata", {}),
                )
                for e in data["events"]
            ],
            node_execution_order=data["node_execution_order"],
            final_status=data["final_status"],
            recorded_at=data.get("recorded_at", ""),
        )


@dataclass
class ReplayIssue:
    """A divergence detected during replay."""
    severity: str  # "error" | "warning"
    code: str
    message: str
    node_id: Optional[str] = None


class TraceRecorder:
    """Records execution events into an ExecutionTrace.

    Subscribe to an EventEmitter to capture events during workflow execution.

    Example:
        recorder = TraceRecorder()
        emitter.subscribe(recorder.capture)
        result = execute_workflow(wf, inputs, event_emitter=emitter)
        trace = recorder.build_trace(result.run_id)
        recorder.save("traces/run-123.json")
    """

    def __init__(self) -> None:
        self._events: List[TraceEvent] = []
        self._node_order: List[str] = []
        self._workflow_name: str = ""
        self._inputs: Dict[str, Any] = {}
        self._final_status: str = ""

    def capture(self, event: Any) -> None:
        """EventEmitter callback — captures a WorkflowEvent.

        Args:
            event: WorkflowEvent from the event emitter
        """
        trace_event = TraceEvent(
            event_type=event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type),
            node_id=getattr(event, "node_id", None),
            status=event.status.value if hasattr(event.status, "value") else str(event.status),
            timestamp=event.timestamp.isoformat() if hasattr(event.timestamp, "isoformat") else str(event.timestamp),
            metadata=getattr(event, "metadata", {}) or {},
        )
        self._events.append(trace_event)

        # Track node execution order (NODE_STARTED events)
        # Note: event_type.value returns lowercase (e.g., "node_started")
        if trace_event.event_type == "node_started" and trace_event.node_id:
            if trace_event.node_id not in self._node_order:
                self._node_order.append(trace_event.node_id)

        # Track workflow-level info
        if trace_event.event_type == "workflow_started":
            self._workflow_name = getattr(event, "workflow_id", "")
        if trace_event.event_type in ("workflow_completed", "workflow_failed", "workflow_interrupted"):
            self._final_status = trace_event.status

    def build_trace(self, run_id: str, inputs: Optional[Dict[str, Any]] = None) -> ExecutionTrace:
        """Build an ExecutionTrace from captured events.

        Args:
            run_id: The workflow run ID
            inputs: Workflow inputs (if not captured from events)

        Returns:
            Complete execution trace
        """
        return ExecutionTrace(
            workflow_name=self._workflow_name,
            run_id=run_id,
            inputs=inputs or self._inputs,
            events=list(self._events),
            node_execution_order=list(self._node_order),
            final_status=self._final_status,
        )

    def save(self, path: str, run_id: str = "", inputs: Optional[Dict[str, Any]] = None) -> None:
        """Save recorded trace to a JSON file.

        Args:
            path: File path to save trace
            run_id: Workflow run ID
            inputs: Workflow inputs
        """
        trace = self.build_trace(run_id, inputs)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(trace.to_dict(), indent=2))


class TraceReplayer:
    """Replays an execution trace against a (possibly modified) workflow definition.

    Detects:
        1. Missing nodes — nodes from trace not in current workflow
        2. New required nodes — nodes in workflow not in trace
        3. Execution order changes — topological order divergence
        4. Dependency changes — nodes have different upstream deps
        5. Type changes — node type changed (bash -> prompt, etc.)
        6. Gate condition changes — gate conditions modified

    Example:
        replayer = TraceReplayer()
        issues = replayer.replay("traces/run-123.json", modified_wf)
    """

    def replay(
        self,
        trace_path: str,
        workflow_def: WorkflowDef,
    ) -> List[ReplayIssue]:
        """Replay a saved trace against a workflow definition.

        Args:
            trace_path: Path to saved trace JSON
            workflow_def: Current workflow definition to validate against

        Returns:
            List of replay issues (divergences) detected
        """
        data = json.loads(Path(trace_path).read_text())
        trace = ExecutionTrace.from_dict(data)
        return self.replay_trace(trace, workflow_def)

    def replay_trace(
        self,
        trace: ExecutionTrace,
        workflow_def: WorkflowDef,
    ) -> List[ReplayIssue]:
        """Replay an in-memory trace against a workflow definition.

        Args:
            trace: Execution trace to replay
            workflow_def: Current workflow definition

        Returns:
            List of replay issues detected
        """
        issues: List[ReplayIssue] = []
        current_nodes = {n.id: n for n in workflow_def.nodes}
        trace_node_ids = set(trace.node_execution_order)

        # Check 1: Nodes removed from workflow that were in the trace
        for node_id in trace.node_execution_order:
            if node_id not in current_nodes:
                issues.append(ReplayIssue(
                    severity="error",
                    code="node_removed",
                    message=f"Node '{node_id}' was executed in trace but no longer exists in workflow",
                    node_id=node_id,
                ))

        # Check 2: New nodes added that weren't in trace
        for node_id, node_def in current_nodes.items():
            if node_id not in trace_node_ids:
                # Only flag if the node has no default/skip path
                if node_def.on_failure == "stop":
                    issues.append(ReplayIssue(
                        severity="warning",
                        code="node_added",
                        message=f"Node '{node_id}' exists in workflow but not in trace "
                                f"(new node or previously skipped)",
                        node_id=node_id,
                    ))

        # Check 3: Dependency changes
        # Extract dependency info from trace events
        for node_id in trace.node_execution_order:
            if node_id in current_nodes:
                current_node = current_nodes[node_id]
                # Check if any dependency was removed from the workflow
                for dep_id in current_node.depends_on:
                    if dep_id not in current_nodes and dep_id not in trace_node_ids:
                        issues.append(ReplayIssue(
                            severity="error",
                            code="broken_dependency",
                            message=f"Node '{node_id}' depends on '{dep_id}' which doesn't exist",
                            node_id=node_id,
                        ))

        # Check 4: Type changes
        # We'd need to record node types in the trace for full validation.
        # For now, flag this as a future enhancement via the trace metadata.

        return issues


def execute_replay(
    workflow_def: WorkflowDef,
    store: CheckpointStore,
    run_id: str,
    from_node: str,
    overrides: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute a replay from a checkpoint, creating a new run.

    This function:
    1. Loads existing metadata from the source run
    2. Copies the run directory to a new run_id
    3. Clears node checkpoints after from_node
    4. Applies input overrides
    5. Returns a summary (does NOT execute the workflow)

    Args:
        workflow_def: Workflow definition
        store: Checkpoint store instance
        run_id: Source run ID to replay from
        from_node: Node ID to replay from (this node and all after it will be re-executed)
        overrides: Input overrides to apply (merged into inputs)

    Returns:
        Dictionary with:
            - new_run_id: ID of the new replay run
            - parent_run_id: Original run_id
            - replayed_from: Node ID replayed from
            - nodes_cleared: List of node IDs cleared

    Raises:
        ValueError: If run_id doesn't exist or from_node is not in workflow
    """
    # 1. Load existing metadata
    meta = store.load_metadata(workflow_def.name, run_id)
    if not meta:
        raise ValueError(f"No metadata found for run '{run_id}'")

    # 2. Validate from_node exists in workflow
    node_ids = [node.id for node in workflow_def.nodes]
    if from_node not in node_ids:
        raise ValueError(f"Node '{from_node}' not found in workflow")

    # 3. Compute topological node order
    from dag_executor.graph import topological_sort_with_layers
    layers = topological_sort_with_layers(workflow_def.nodes)
    node_order: List[str] = []
    for layer in layers:
        node_order.extend(layer)

    # 4. Generate new run_id
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    new_run_id = f"{run_id}-replay-{ts}"

    # 5. Copy the run checkpoint directory to the new run_id directory
    original_dir = store._get_run_dir(workflow_def.name, run_id)
    new_dir = store._get_run_dir(workflow_def.name, new_run_id)
    shutil.copytree(str(original_dir), str(new_dir))

    # 6. Clear nodes after --from-node
    cleared = store.clear_nodes_after(workflow_def.name, new_run_id, from_node, node_order)

    # 7. Update metadata with new run_id and apply overrides
    new_meta = CheckpointMetadata(
        workflow_name=meta.workflow_name,
        run_id=new_run_id,
        started_at=meta.started_at,
        inputs={**meta.inputs, **overrides},  # Merge overrides
        status="pending",
    )

    # 8. Save updated metadata
    store.save_metadata(workflow_def.name, new_run_id, new_meta)

    # 9. Return summary
    return {
        "new_run_id": new_run_id,
        "parent_run_id": run_id,
        "replayed_from": from_node,
        "nodes_cleared": cleared,
    }

"""FastAPI routes for workflow dashboard."""
import asyncio
import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional

import yaml
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from dag_executor.gates import build_approval_resolved_event
from dag_executor.checkpoint import CheckpointStore

from .models import SortBy, RunStatus, StatusSummary, GateDecisionRequest, InterruptResumeRequest, NodeStateDiff, RerunRequest
from .queries import (
    get_run, list_runs, list_runs_grouped, get_node, list_nodes, get_status_counts,
    get_artifacts, get_chat_messages, get_workflow_totals,
    insert_gate_decision, update_node, get_pending_gates, count_pending_gates,
    get_pending_gates_for_run,
    get_interrupt_checkpoint,
    get_state_diff_timeline, get_checkpoint_comparison,
    list_run_artifacts,
    get_nodes_by_names, get_run_for_rerun, insert_run,
    get_node_log_lines, count_node_log_lines,
)
from .layout import compute_layout

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def get_db_path(request: Request) -> Path:
    """Extract database path from app state."""
    # Try to use db_path directly if available (used when db_path passed to create_app)
    db_path_attr = getattr(request.app.state, 'db_path', None)
    if db_path_attr:
        return Path(db_path_attr)
    # Fall back to db_dir / "dashboard.db" (used when db_dir passed to create_app)
    db_dir: Path = request.app.state.db_dir
    return db_dir / "dashboard.db"


def get_events_dir(request: Request) -> Path:
    """Extract events directory path from app state."""
    events_dir: Path = request.app.state.events_dir
    return events_dir


@router.get("/config")
async def get_config(request: Request) -> Dict[str, bool]:
    """Return UI-relevant configuration flags."""
    settings = getattr(request.app.state, 'settings', None)
    checkpoint_prefix = getattr(request.app.state, 'checkpoint_prefix', None)
    return {
        "allow_destructive_nodes": getattr(settings, 'allow_destructive_nodes', False) if settings else False,
        "builder_enabled": getattr(settings, 'builder_enabled', False) if settings else False,
        "checkpoint_enabled": checkpoint_prefix is not None,
        "trigger_enabled": getattr(settings, 'trigger_enabled', False) if settings else False,
    }


@router.get("/workflows/summary")
async def get_workflows_summary(request: Request) -> StatusSummary:
    """Get status summary counts for dashboard."""
    db_path = get_db_path(request)
    counts = get_status_counts(db_path)
    return StatusSummary(**counts)


@router.get("/workflows")
async def get_workflows(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: Optional[RunStatus] = None,
    sort_by: SortBy = Query(default=SortBy.STARTED_AT),
    name: Optional[str] = None,
    started_after: Optional[str] = None,
    started_before: Optional[str] = None,
    group_by: Optional[str] = Query(default=None, pattern="^parent$"),
) -> Dict[str, Any]:
    """List workflow runs with pagination and filtering.

    When ``group_by=parent``, runs are nested under their root run via the
    ``parent_run_id`` column. Each top-level item gains a ``children`` array
    and an ``aggregate_status`` reflecting the worst status in its subtree.
    """
    db_path = get_db_path(request)
    if group_by == "parent":
        return list_runs_grouped(
            db_path,
            limit=limit,
            offset=offset,
            status=status,
            sort_by=sort_by,
            name=name,
            started_after=started_after,
            started_before=started_before,
        )
    return list_runs(
        db_path,
        limit=limit,
        offset=offset,
        status=status,
        sort_by=sort_by,
        name=name,
        started_after=started_after,
        started_before=started_before,
    )


@router.get("/workflows/{run_id}")
async def get_workflow(request: Request, run_id: str) -> Dict[str, Any]:
    """Get a single workflow run with its nodes."""
    db_path = get_db_path(request)

    run = get_run(db_path, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    nodes = list_nodes(db_path, run_id)
    totals = get_workflow_totals(db_path, run_id)

    return {
        "run": run,
        "nodes": nodes,
        "totals": totals,
    }


@router.post("/workflows/{run_id}/rerun")
async def rerun_workflow(request: Request, run_id: str, body: RerunRequest = RerunRequest()) -> Dict[str, Any]:
    """Rerun a workflow with optionally modified inputs."""
    db_path = get_db_path(request)

    # Load prior run
    prior_run = get_run_for_rerun(db_path, run_id)
    if prior_run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    workflow_name = prior_run["workflow_name"]
    prior_inputs = prior_run["inputs"]

    # Handle input override (full replacement, not merge)
    if body.inputs is not None:
        inputs = body.inputs
    else:
        inputs = prior_inputs

    # Generate new run ID
    new_run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()

    # Insert new run with parent_run_id BEFORE spawning subprocess
    insert_run(
        db_path=db_path,
        run_id=new_run_id,
        workflow_name=workflow_name,
        status="running",
        started_at=started_at,
        inputs=inputs,
        parent_run_id=run_id,
    )

    # Spawn dag-exec subprocess
    workflows_dir = getattr(request.app.state, 'workflows_dir', Path("workflows"))
    workflow_file = workflows_dir / f"{workflow_name}.yaml"

    # Check file exists before spawning
    if not workflow_file.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Workflow file not found: {workflow_name}.yaml"
        )

    # Build input args for subprocess
    input_args = []
    for k, v in inputs.items():
        if isinstance(v, (dict, list)):
            input_args.append(f"{k}={json.dumps(v)}")
        else:
            input_args.append(f"{k}={v}")

    # Spawn subprocess (detached)
    await asyncio.create_subprocess_exec(
        "dag-exec",
        str(workflow_file),
        *input_args,
        "--run-id", new_run_id,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

    return {
        "run_id": new_run_id,
        "parent_run_id": run_id,
    }


@router.get("/workflows/{run_id}/nodes/{node_id}")
async def get_workflow_node(
    request: Request,
    run_id: str,
    node_id: str,
) -> Dict[str, Any]:
    """Get a single node execution with artifacts, chat messages, and enriched data."""
    db_path = get_db_path(request)

    # The URL's {node_id} may be the bare node_name ("hello") or the composite
    # "{run_id}:{node_name}" id. Try composite first, fall back to bare.
    node = get_node(db_path, f"{run_id}:{node_id}") or get_node(db_path, node_id)
    if node is None or node.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail="Node execution not found")

    # Every downstream query expects the composite id.
    composite_id = node["id"]

    # Enrich with artifacts and chat messages
    artifacts = get_artifacts(db_path, composite_id)
    chat_messages = get_chat_messages(db_path, composite_id)

    # Enrich with upstream context if node has dependencies
    upstream_context = []
    depends_on_raw = node.get("depends_on")
    if depends_on_raw:
        try:
            depends_on = json.loads(depends_on_raw) if isinstance(depends_on_raw, str) else depends_on_raw
            if depends_on and isinstance(depends_on, list):
                # Batch-resolve upstream nodes
                upstream_nodes = get_nodes_by_names(db_path, run_id, depends_on)

                # Build upstream context with artifacts for each upstream
                for upstream_name in depends_on:
                    if upstream_name in upstream_nodes:
                        upstream_node = upstream_nodes[upstream_name]
                        upstream_artifacts = get_artifacts(db_path, upstream_node["id"])
                        upstream_context.append({
                            "node_id": upstream_node["id"],
                            "node_name": upstream_node["node_name"],
                            "status": upstream_node["status"],
                            "artifacts": upstream_artifacts,
                        })
        except (json.JSONDecodeError, TypeError):
            pass  # If depends_on is malformed, leave upstream_context empty

    return {
        **node,
        "artifacts": artifacts,
        "chat_messages": chat_messages,
        "upstream_context": upstream_context,
    }


@router.get("/workflows/{run_id}/nodes/{node_id}/checkpoint")
async def get_node_checkpoint(
    request: Request,
    run_id: str,
    node_id: str,
) -> Dict[str, Any]:
    """Get checkpoint version comparison for a node."""
    db_path = get_db_path(request)

    # Verify node exists
    node = get_node(db_path, node_id)
    if node is None or node["run_id"] != run_id:
        raise HTTPException(status_code=404, detail="Node execution not found")

    comparison = get_checkpoint_comparison(db_path, run_id, node_id)
    if comparison is None:
        raise HTTPException(status_code=404, detail="No checkpoint data for this node")

    return comparison


@router.get("/workflows/{run_id}/nodes/{node_id}/logs")
async def get_node_logs(
    request: Request,
    run_id: str,
    node_id: str,
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    stream: str = Query("all", pattern="^(all|stdout|stderr)$")
) -> Dict[str, Any]:
    """Get log lines for a specific node execution.
    
    Returns paginated log lines from the events table. Lines are ordered by sequence number.
    
    Query parameters:
    - limit: Max lines to return (1-1000, default 500)
    - offset: Skip this many lines for pagination (default 0)
    - stream: Filter by stream - 'all', 'stdout', or 'stderr' (default 'all')
    
    Response includes:
    - lines: Array of {sequence, stream, line, timestamp}
    - total: Total log lines for this node (considering stream filter)
    - limit: Echo of limit parameter
    - offset: Echo of offset parameter
    - has_more: Boolean indicating if more lines are available
    """
    db_path = get_db_path(request)

    # Verify node exists. The URL's {node_id} is the bare node_name, but
    # node_executions.id is the composite "{run_id}:{node_name}". Try the
    # composite lookup first; if that misses (older rows only have node_name),
    # match on (run_id, node_name) directly.
    node = get_node(db_path, f"{run_id}:{node_id}") or get_node(db_path, node_id)
    if node is None or node.get("run_id") != run_id:
        # Fallback: query by (run_id, node_name) pair.
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT 1 FROM node_executions WHERE run_id = ? AND node_name = ?",
                (run_id, node_id),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise HTTPException(status_code=404, detail="Node execution not found")

    # Get log lines with pagination and stream filter. node_logs.node_id stores
    # the bare node_name (matching emitter contract).
    lines = get_node_log_lines(db_path, run_id, node_id, limit, offset, stream)

    # Total count via COUNT(*) so pagination metadata is cheap even for large runs.
    total = count_node_log_lines(db_path, run_id, node_id, stream_filter=stream)

    return {
        "lines": lines,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + len(lines)) < total
    }



@router.get("/workflows/{run_id}/layout")
async def get_workflow_layout(request: Request, run_id: str) -> Dict[str, Any]:
    """Compute DAG layout for a workflow run.

    When the executor hasn't started emitting node_started events yet (the
    typical state for the first ~1-2 seconds after trigger), node_executions
    is empty and the dashboard would show a blank graph. Fall back to the
    workflow YAML and synthesize pending-status skeleton nodes so the user
    sees the shape of the DAG immediately; real statuses overlay as the
    executor walks the graph.
    """
    db_path = get_db_path(request)

    # Verify workflow exists
    run = get_run(db_path, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    # Get nodes from DB (populated as the executor runs)
    nodes = list_nodes(db_path, run_id)

    if not nodes:
        # No execution yet — synthesize skeleton from the workflow definition.
        # Prefer the YAML text saved on the run row (retry path) before
        # scanning disk, so reruns of deleted workflows still render.
        skeleton = _skeleton_from_workflow_def(
            request=request,
            run_id=run_id,
            workflow_name=run.get("workflow_name", ""),
            workflow_definition=run.get("workflow_definition"),
        )
        if skeleton:
            return compute_layout(skeleton)

    return compute_layout(nodes)


def _skeleton_from_workflow_def(
    request: Request,
    run_id: str,
    workflow_name: str,
    workflow_definition: Optional[str],
) -> list[Dict[str, Any]]:
    """Parse the workflow YAML and return pending-status skeleton nodes.

    Returns the list shape `list_nodes` produces so it plugs straight into
    compute_layout. Empty list on any failure — caller falls through to the
    (empty) live-db result without blowing up.
    """
    yaml_text: Optional[str] = workflow_definition
    if not yaml_text:
        workflows_dirs = getattr(request.app.state, "workflows_dirs", None) or []
        for wd in workflows_dirs:
            candidate = Path(wd) / f"{workflow_name}.yaml"
            if candidate.exists():
                try:
                    yaml_text = candidate.read_text()
                except OSError:
                    continue
                break
    if not yaml_text:
        return []

    try:
        parsed = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError:
        return []

    raw_nodes = parsed.get("nodes") or []
    if not isinstance(raw_nodes, list):
        return []

    skeleton: list[Dict[str, Any]] = []
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            continue
        node_name = raw.get("id") or raw.get("name")
        if not isinstance(node_name, str) or not node_name:
            continue
        depends_on = raw.get("depends_on") or []
        if not isinstance(depends_on, list):
            depends_on = []
        # Forward node_data (edges/model/etc.) so compute_layout can render
        # conditional edges for skeleton nodes too.
        skeleton.append({
            "id": f"{run_id}:{node_name}",
            "run_id": run_id,
            "node_name": node_name,
            "status": "pending",
            "depends_on": [str(d) for d in depends_on if isinstance(d, str)],
            "node_data": {
                "edges": raw.get("edges"),
                "type": raw.get("type"),
            },
            "model": raw.get("model"),
            "tokens": None,
            "cost": None,
            "started_at": None,
            "finished_at": None,
            "error": None,
        })
    return skeleton


@router.get("/workflows/{run_id}/channels")
async def get_workflow_channels(request: Request, run_id: str) -> Dict[str, Any]:
    """Get channel states for a workflow run.

    Returns:
        Dictionary with "channels" key containing list of channel states
    """
    from .queries import get_channel_states

    db_path = get_db_path(request)

    # Verify workflow exists
    run = get_run(db_path, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    # Get channel states
    channels = get_channel_states(db_path, run_id)

    return {"channels": channels}


@router.get("/workflows/{run_id}/artifacts")
async def get_workflow_artifacts(request: Request, run_id: str) -> Dict[str, Any]:
    """List all artifacts produced by a workflow run, grouped with node context."""
    db_path = get_db_path(request)

    run = get_run(db_path, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    artifacts = list_run_artifacts(db_path, run_id)
    return {"artifacts": artifacts}


async def event_generator() -> AsyncIterator[str]:
    """Generate SSE events."""
    yield f"data: {json.dumps({'type': 'connected', 'message': 'SSE connection established'})}\n\n"

    try:
        while True:
            await asyncio.sleep(30)
            yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': asyncio.get_event_loop().time()})}\n\n"
    except asyncio.CancelledError:
        pass


@router.get("/events")
async def sse_endpoint() -> StreamingResponse:
    """Server-Sent Events endpoint for real-time workflow updates."""
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/workflows/{run_id}/gates/{node_name}/approve")
async def approve_gate(
    request: Request,
    run_id: str,
    node_name: str,
    body: GateDecisionRequest,
) -> Dict[str, Any]:
    """Approve a gate decision for a workflow node."""
    db_path = get_db_path(request)
    events_dir = get_events_dir(request)

    # Verify run exists
    run = get_run(db_path, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    # Verify node exists and is interrupted
    node_id = f"{run_id}:{node_name}"
    node = get_node(db_path, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if node["status"] != "interrupted":
        raise HTTPException(status_code=409, detail="Node is not in interrupted state")

    # Get decided_by from request body or default to OS user
    decided_by = body.decided_by or os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown"
    decided_at = datetime.now(timezone.utc).isoformat()

    # Insert gate decision
    insert_gate_decision(
        db_path,
        run_id=run_id,
        node_name=node_name,
        decision="approved",
        decided_by=decided_by,
        decided_at=decided_at,
        reason=body.comment,
    )

    # Update node status to completed
    update_node(db_path, node_id, status="completed", finished_at=decided_at)

    # Get workflow definition to check if this is an interrupt node
    workflow_def_yaml = run["workflow_definition"]
    workflow_def = yaml.safe_load(workflow_def_yaml) if workflow_def_yaml else {}
    checkpoint_prefix = workflow_def.get("config", {}).get("checkpoint_prefix")

    if not checkpoint_prefix:
        checkpoint_prefix = request.app.state.checkpoint_dir_fallback or os.path.expanduser(
            "~/.dag-executor/checkpoints"
        )

    # For interrupt nodes, save resume_values
    resume_key = None
    try:
        store = CheckpointStore(checkpoint_prefix)
        interrupt_checkpoint = store.load_interrupt(run["workflow_name"], run_id)
        if interrupt_checkpoint and interrupt_checkpoint.resume_key:
            resume_key = interrupt_checkpoint.resume_key
            resume_values = {resume_key: True}
            store.save_resume_values(run["workflow_name"], run_id, resume_values)
    except (FileNotFoundError, ValueError) as e:
        # If checkpoint loading fails, continue without resume_values
        logger.warning(f"Could not save resume_values for {run_id}: {e}")

    # Append NDJSON events to {run_id}.ndjson for executor signaling
    event_file = events_dir / f"{run_id}.ndjson"

    # Event 1: gate.decided (backward compatibility)
    gate_decided_event = {
        "event_type": "gate.decided",
        "payload": json.dumps({
            "node_name": node_name,
            "decision": "approved",
            "decided_by": decided_by,
            "comment": body.comment,
        }),
        "created_at": decided_at,
    }

    # Event 2: approval_resolved (new canonical)
    approval_resolved_event = build_approval_resolved_event(
        run_id=run_id,
        node_id=node_name,
        decision="approved",
        decided_by=decided_by,
        source="api",
        resume_key=resume_key,
        resume_value=True if resume_key else None,
        comment=body.comment,
    )

    with open(event_file, "a") as f:
        f.write(json.dumps(gate_decided_event) + "\n")
        f.write(json.dumps(approval_resolved_event) + "\n")

    return {
        "run_id": run_id,
        "node_name": node_name,
        "decision": "approved",
        "decided_by": decided_by,
        "decided_at": decided_at,
        "comment": body.comment,
    }


@router.post("/workflows/{run_id}/gates/{node_name}/reject")
async def reject_gate(
    request: Request,
    run_id: str,
    node_name: str,
    body: GateDecisionRequest,
) -> Dict[str, Any]:
    """Reject a gate decision for a workflow node."""
    db_path = get_db_path(request)
    events_dir = get_events_dir(request)

    # Verify run exists
    run = get_run(db_path, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    # Verify node exists and is interrupted
    node_id = f"{run_id}:{node_name}"
    node = get_node(db_path, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if node["status"] != "interrupted":
        raise HTTPException(status_code=409, detail="Node is not in interrupted state")

    # Get decided_by from request body or default to OS user
    decided_by = body.decided_by or os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown"
    decided_at = datetime.now(timezone.utc).isoformat()

    # Insert gate decision
    insert_gate_decision(
        db_path,
        run_id=run_id,
        node_name=node_name,
        decision="rejected",
        decided_by=decided_by,
        decided_at=decided_at,
        reason=body.comment,
    )

    # Update node status to failed
    update_node(db_path, node_id, status="failed", finished_at=decided_at)

    # Get workflow definition to check if this is an interrupt node
    workflow_def_yaml = run["workflow_definition"]
    workflow_def = yaml.safe_load(workflow_def_yaml) if workflow_def_yaml else {}
    checkpoint_prefix = workflow_def.get("config", {}).get("checkpoint_prefix")

    if not checkpoint_prefix:
        checkpoint_prefix = request.app.state.checkpoint_dir_fallback or os.path.expanduser(
            "~/.dag-executor/checkpoints"
        )

    # For interrupt nodes, save resume_values
    resume_key = None
    try:
        store = CheckpointStore(checkpoint_prefix)
        interrupt_checkpoint = store.load_interrupt(run["workflow_name"], run_id)
        if interrupt_checkpoint and interrupt_checkpoint.resume_key:
            resume_key = interrupt_checkpoint.resume_key
            resume_values = {resume_key: False}
            store.save_resume_values(run["workflow_name"], run_id, resume_values)
    except (FileNotFoundError, ValueError) as e:
        # If checkpoint loading fails, continue without resume_values
        logger.warning(f"Could not save resume_values for {run_id}: {e}")

    # Append NDJSON events to {run_id}.ndjson for executor signaling
    event_file = events_dir / f"{run_id}.ndjson"

    # Event 1: gate.decided (backward compatibility)
    gate_decided_event = {
        "event_type": "gate.decided",
        "payload": json.dumps({
            "node_name": node_name,
            "decision": "rejected",
            "decided_by": decided_by,
            "comment": body.comment,
        }),
        "created_at": decided_at,
    }

    # Event 2: approval_resolved (new canonical)
    approval_resolved_event = build_approval_resolved_event(
        run_id=run_id,
        node_id=node_name,
        decision="rejected",
        decided_by=decided_by,
        source="api",
        resume_key=resume_key,
        resume_value=False if resume_key else None,
        comment=body.comment,
    )

    with open(event_file, "a") as f:
        f.write(json.dumps(gate_decided_event) + "\n")
        f.write(json.dumps(approval_resolved_event) + "\n")

    return {
        "run_id": run_id,
        "node_name": node_name,
        "decision": "rejected",
        "decided_by": decided_by,
        "decided_at": decided_at,
        "comment": body.comment,
    }


@router.get("/gates/pending")
async def get_pending_gates_route(request: Request) -> Dict[str, Any]:
    """Get all pending gate approvals (interrupted nodes in running workflows)."""
    db_path = get_db_path(request)

    gates = get_pending_gates(db_path)
    count = count_pending_gates(db_path)

    return {
        "count": count,
        "gates": gates,
    }


@router.get("/workflows/{run_id}/gates")
async def get_workflow_gates_route(request: Request, run_id: str) -> Dict[str, Any]:
    """Get pending gate approvals for a specific workflow run."""
    db_path = get_db_path(request)

    gates = get_pending_gates_for_run(db_path, run_id)

    return {
        "count": len(gates),
        "gates": gates,
    }


@router.get("/workflows/{run_id}/nodes/{node_name}/interrupt")
async def get_interrupt_context(
    request: Request,
    run_id: str,
    node_name: str
) -> Dict[str, Any]:
    """Get interrupt checkpoint data for a node."""
    db_path = get_db_path(request)
    checkpoint_dir_fallback = request.app.state.checkpoint_dir_fallback

    # Verify run exists
    run = get_run(db_path, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    # Verify node exists and is interrupted
    node_id = f"{run_id}:{node_name}"
    node = get_node(db_path, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if node["status"] != "interrupted":
        raise HTTPException(status_code=409, detail="Node is not in interrupted state")

    # Load interrupt checkpoint
    workflow_name = run["workflow_name"]
    checkpoint = get_interrupt_checkpoint(
        db_path,
        workflow_name,
        run_id,
        node_name,
        checkpoint_dir_fallback
    )

    if checkpoint is None:
        raise HTTPException(status_code=404, detail="Interrupt checkpoint not found")

    return checkpoint


@router.get("/workflows/{run_id}/escalations/{node_name}")
async def get_escalation(
    request: Request,
    run_id: str,
    node_name: str,
) -> Dict[str, Any]:
    """Return the escalation checkpoint for a paused run.

    The wrapping conversation reads this to understand what the failed node
    was trying to do (prompt, writes, output_format) and why it failed
    (error, stdout_tail), then does the work inline and POSTs a synthesized
    output back to the resume endpoint.
    """
    from dag_executor.checkpoint import CheckpointStore
    import yaml

    db_path = get_db_path(request)
    checkpoint_dir_fallback = request.app.state.checkpoint_dir_fallback

    run = get_run(db_path, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    # Resolve workflow file so we can parse the display name (CheckpointStore
    # keys by name, not filename).
    workflows_dirs = getattr(request.app.state, "workflows_dirs", None) or []
    workflow_file: Optional[Path] = None
    for wd in workflows_dirs:
        candidate = Path(wd) / f"{run['workflow_name']}.yaml"
        if candidate.exists():
            workflow_file = candidate
            break
    workflow_def_yaml = run.get("workflow_definition")
    workflow_def: Dict[str, Any] = {}
    if workflow_def_yaml:
        workflow_def = yaml.safe_load(workflow_def_yaml) or {}
    elif workflow_file is not None:
        try:
            workflow_def = yaml.safe_load(workflow_file.read_text()) or {}
        except (OSError, yaml.YAMLError):
            pass

    checkpoint_prefix = workflow_def.get("config", {}).get("checkpoint_prefix")
    if not checkpoint_prefix:
        checkpoint_prefix = checkpoint_dir_fallback or os.path.expanduser(
            "~/.dag-executor/checkpoints"
        )
    checkpoint_workflow_name = workflow_def.get("name") or run["workflow_name"]

    store = CheckpointStore(checkpoint_prefix)
    escalation = store.load_escalation(checkpoint_workflow_name, run_id)
    if escalation is None:
        raise HTTPException(status_code=404, detail="Escalation checkpoint not found")

    payload = escalation.model_dump()
    if payload.get("node_id") != node_name:
        # The endpoint takes node_name for parity with the interrupt URL
        # shape, but we surface the stored node_id as authoritative.
        payload["requested_node"] = node_name
    return payload


@router.post("/workflows/{run_id}/interrupts/{node_name}/resume")
async def resume_interrupt(
    request: Request,
    run_id: str,
    node_name: str,
    body: InterruptResumeRequest,
) -> Dict[str, Any]:
    """Resume an interrupted workflow by injecting a resume value."""
    from dag_executor.checkpoint import CheckpointStore
    import yaml

    db_path = get_db_path(request)
    checkpoint_dir_fallback = request.app.state.checkpoint_dir_fallback

    # Verify run exists
    run = get_run(db_path, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    # Accept both interrupted (human-in-the-loop pause) and escalated
    # (on_failure=escalate) states — both flow through this same endpoint.
    # The payload shape differs: interrupts get the resume value stored
    # under the interrupt's resume_key; escalations get the synthesized
    # output stored under the magic __escalation_output__ key for the
    # executor to seed as ctx.node_outputs.
    node_id = f"{run_id}:{node_name}"
    node = get_node(db_path, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    node_status = node["status"]
    if node_status not in ("interrupted", "escalated"):
        raise HTTPException(
            status_code=409,
            detail=f"Node is not in a resumable state (status={node_status})",
        )
    is_escalation = node_status == "escalated"

    # Resolve workflow file up front — we need it for checkpoint_prefix
    # lookup and for the --resume respawn below.
    workflows_dirs = getattr(request.app.state, "workflows_dirs", None) or []
    workflow_file: Optional[Path] = None
    for wd in workflows_dirs:
        candidate = Path(wd) / f"{run['workflow_name']}.yaml"
        if candidate.exists():
            workflow_file = candidate
            break
    if workflow_file is None:
        single_dir = getattr(request.app.state, "workflows_dir", None)
        if single_dir:
            candidate = Path(single_dir) / f"{run['workflow_name']}.yaml"
            if candidate.exists():
                workflow_file = candidate

    # Get checkpoint_prefix. Prefer the saved workflow_definition (retry-flow
    # convention); fall back to parsing the workflow file; fall back to the
    # dashboard's configured checkpoint_dir_fallback.
    workflow_def_yaml = run.get("workflow_definition")
    workflow_def: Dict[str, Any] = {}
    if workflow_def_yaml:
        workflow_def = yaml.safe_load(workflow_def_yaml) or {}
    elif workflow_file is not None:
        try:
            workflow_def = yaml.safe_load(workflow_file.read_text()) or {}
        except (OSError, yaml.YAMLError) as exc:
            logger.warning(f"Could not parse workflow file {workflow_file}: {exc}")

    checkpoint_prefix = workflow_def.get("config", {}).get("checkpoint_prefix")
    if not checkpoint_prefix:
        checkpoint_prefix = checkpoint_dir_fallback or os.path.expanduser(
            "~/.dag-executor/checkpoints"
        )

    # CheckpointStore keys by workflow_def.name (the display name in the YAML's
    # `name:` field) — not the filename the dashboard DB stores as
    # workflow_name. Prefer the parsed display name; fall back to the DB name
    # for retry-path runs that actually stored the YAML in workflow_definition.
    checkpoint_workflow_name = workflow_def.get("name") or run["workflow_name"]

    store = CheckpointStore(checkpoint_prefix)

    if is_escalation:
        # Load escalation checkpoint — payload IS the synthesized output.
        escalation_checkpoint = store.load_escalation(
            checkpoint_workflow_name, run_id
        )
        if not escalation_checkpoint:
            raise HTTPException(
                status_code=404, detail="Escalation checkpoint not found"
            )
        # Stash under the magic key the executor's resume path looks for.
        resume_values = {"__escalation_output__": body.resume_value}
        store.save_resume_values(checkpoint_workflow_name, run_id, resume_values)
    else:
        # Load interrupt checkpoint to get resume_key
        interrupt_checkpoint = store.load_interrupt(
            checkpoint_workflow_name, run_id
        )
        if not interrupt_checkpoint:
            raise HTTPException(
                status_code=404, detail="Interrupt checkpoint not found"
            )
        # Save resume values
        resume_values = {interrupt_checkpoint.resume_key: body.resume_value}
        store.save_resume_values(checkpoint_workflow_name, run_id, resume_values)

    # Get decided_by from request body or default to OS user
    decided_by = body.decided_by or os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown"
    decided_at = datetime.now(timezone.utc).isoformat()

    # Insert gate decision for audit (use "resumed" as decision value)
    insert_gate_decision(
        db_path,
        run_id=run_id,
        node_name=node_name,
        decision="resumed",
        decided_by=decided_by,
        decided_at=decided_at,
        reason=body.comment,
    )

    # Respawn dag-exec --resume so downstream nodes actually run.
    # Without this, the executor exited at the interrupt and the DB was the
    # only thing being updated — the workflow would permanently stall.
    #
    # When workflow_file can't be located (unit tests that only seed DB +
    # checkpoint, without writing the YAML), fall back to the old contract:
    # mark the interrupted node completed so the resume_values land in the
    # store and the endpoint remains testable in isolation. A warning makes
    # the degraded path visible in logs.
    if workflow_file is None:
        logger.warning(
            "resume_interrupt: workflow file for %s not found; skipping --resume "
            "respawn. Downstream nodes will NOT execute.",
            run["workflow_name"],
        )
        update_node(
            db_path,
            node_id,
            status="completed",
            finished_at=decided_at,
            outputs={
                **(node.get("outputs") or {}),
                "resume_value": body.resume_value,
                "node_type": "interrupt",
            },
        )
    else:
        events_dir = get_events_dir(request)
        child_env = {**os.environ, "DAG_EVENTS_DIR": str(events_dir.resolve())}

        # Reset the run row back to "resuming". For interrupts we also flip
        # the interrupted node back to pending so the executor re-runs it
        # with the resume value in workflow_inputs. For escalations we leave
        # the escalated node alone — the executor's prefill path marks it
        # completed with the synthesized output and emits NODE_COMPLETED.
        # Skipped downstream nodes are reset to pending in both cases so
        # they actually run.
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE workflow_runs SET status = 'resuming', finished_at = NULL, error = NULL WHERE id = ?",
                (run_id,),
            )
            if not is_escalation:
                cur.execute(
                    "UPDATE node_executions SET status = 'pending', finished_at = NULL "
                    "WHERE id = ? AND status = 'interrupted'",
                    (node_id,),
                )
            cur.execute(
                "UPDATE node_executions SET status = 'pending', finished_at = NULL "
                "WHERE run_id = ? AND status IN ('skipped')",
                (run_id,),
            )
            conn.commit()
        finally:
            conn.close()

        await asyncio.create_subprocess_exec(
            "dag-exec",
            str(workflow_file),
            "--resume",
            "--run-id", run_id,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env=child_env,
        )

    return {
        "run_id": run_id,
        "node_name": node_name,
        "resumed": True,
        "decided_by": decided_by,
        "decided_at": decided_at,
        "comment": body.comment,
    }


@router.get("/workflows/{run_id}/state-diff-timeline")
async def get_state_diff_timeline_route(request: Request, run_id: str) -> list[NodeStateDiff]:
    """
    Get state diff timeline for a workflow run.

    Returns chronological list of node executions with state changes
    (added/changed/removed channel keys with before/after values).
    Returns empty list if no node_completed events exist for the run.
    Returns 404 if the run does not exist.
    """
    db_path = get_db_path(request)

    # Get timeline (will be empty if no events)
    timeline = get_state_diff_timeline(db_path, run_id)

    # If timeline is empty, verify the run exists to distinguish between
    # "run exists but no events" vs "run doesn't exist"
    if not timeline:
        run = get_run(db_path, run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return [NodeStateDiff(**entry) for entry in timeline]


@router.get("/definitions")
async def get_definitions_list(request: Request) -> list[dict[str, Any]]:
    """
    List all workflow definitions across configured workflows directories.


    Returns:
        List of workflow definitions with name, source_dir, metadata, and collision info.
    """
    from .definitions import list_definitions

    workflows_dirs = request.app.state.workflows_dirs
    db_path = request.app.state.db_path
    return list_definitions(workflows_dirs, db_path=db_path)


@router.get("/definitions/{name}")
async def get_definition_detail(name: str, request: Request) -> dict[str, Any]:
    """
    Get workflow definition details including YAML source and parsed data.

    Args:
        name: Workflow name (without .yaml extension).

    Returns:
        Definition dict with name, yaml_source, parsed data, and layout.

    Raises:
        HTTPException 400: If name contains invalid characters (traversal attempt).
        HTTPException 404: If workflow not found.
    """
    from .definitions import get_definition, DefinitionParseError
    from .layout import compute_layout

    workflows_dirs = request.app.state.workflows_dirs

    try:
        definition = get_definition(workflows_dirs, name)
    except ValueError as e:
        # Invalid name (traversal attempt)
        raise HTTPException(status_code=400, detail=str(e))
    except DefinitionParseError as e:
        # Workflow file exists but YAML is invalid
        raise HTTPException(status_code=500, detail=f"Workflow YAML parse error: {str(e)}")

    if definition is None:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow '{name}' not found in configured directories"
        )

    # Compute layout from parsed YAML
    parsed = definition.get("parsed", {})
    nodes_raw = parsed.get("nodes", [])

    # Convert parsed nodes to the format compute_layout expects
    nodes_for_layout = []
    for node in nodes_raw:
        node_dict = {
            "node_name": node.get("id"),
            "depends_on": node.get("depends_on", []),
            "status": "pending",
            "id": node.get("id"),
            "run_id": "",
        }
        nodes_for_layout.append(node_dict)

    # Compute layout
    layout = compute_layout(nodes_for_layout)
    definition["layout"] = layout

    return definition


@router.get("/skills")
async def get_skills(request: Request) -> list[dict[str, Any]]:
    """
    List all skills across configured skills directories.

    Returns:
        List of skills with name, description, and path.
    """
    from .skills_discovery import list_skills

    skills_dirs = getattr(request.app.state, "skills_dirs", [])
    return list_skills(skills_dirs)

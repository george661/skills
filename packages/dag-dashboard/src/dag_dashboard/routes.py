"""FastAPI routes for workflow dashboard."""
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from .models import SortBy, RunStatus, StatusSummary, GateDecisionRequest, InterruptResumeRequest, NodeStateDiff
from .queries import (
    get_run, list_runs, get_node, list_nodes, get_status_counts,
    get_artifacts, get_chat_messages, get_workflow_totals,
    insert_gate_decision, update_node, get_pending_gates, count_pending_gates,
    get_interrupt_checkpoint,
    get_state_diff_timeline, get_checkpoint_comparison,
    list_run_artifacts,
    get_nodes_by_names,
    get_node_log_lines,
)
from .layout import compute_layout

router = APIRouter(prefix="/api")


def get_db_path(request: Request) -> Path:
    """Extract database path from app state."""
    db_dir: Path = request.app.state.db_dir
    return db_dir / "dashboard.db"


def get_events_dir(request: Request) -> Path:
    """Extract events directory path from app state."""
    events_dir: Path = request.app.state.events_dir
    return events_dir


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
) -> Dict[str, Any]:
    """List workflow runs with pagination and filtering."""
    db_path = get_db_path(request)
    result = list_runs(
        db_path,
        limit=limit,
        offset=offset,
        status=status,
        sort_by=sort_by,
        name=name,
        started_after=started_after,
        started_before=started_before,
    )
    return result


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


@router.get("/workflows/{run_id}/nodes/{node_id}")
async def get_workflow_node(
    request: Request,
    run_id: str,
    node_id: str,
) -> Dict[str, Any]:
    """Get a single node execution with artifacts, chat messages, and enriched data."""
    db_path = get_db_path(request)

    node = get_node(db_path, node_id)
    if node is None or node["run_id"] != run_id:
        raise HTTPException(status_code=404, detail="Node execution not found")

    # Enrich with artifacts and chat messages
    artifacts = get_artifacts(db_path, node_id)
    chat_messages = get_chat_messages(db_path, node_id)

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
    
    # Verify node exists
    node = get_node(db_path, node_id)
    if node is None or node["run_id"] != run_id:
        raise HTTPException(status_code=404, detail="Node execution not found")
    
    # Get log lines with pagination and stream filter
    lines = get_node_log_lines(db_path, run_id, node_id, limit, offset, stream)
    
    # Get total count for pagination metadata
    total_lines = get_node_log_lines(db_path, run_id, node_id, limit=999999, offset=0, stream_filter=stream)
    total = len(total_lines)
    
    return {
        "lines": lines,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + len(lines)) < total
    }



@router.get("/workflows/{run_id}/layout")
async def get_workflow_layout(request: Request, run_id: str) -> Dict[str, Any]:
    """Compute DAG layout for a workflow run."""
    db_path = get_db_path(request)

    # Verify workflow exists
    run = get_run(db_path, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    # Get nodes and compute layout
    nodes = list_nodes(db_path, run_id)
    layout_data = compute_layout(nodes)

    return layout_data


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
    decided_by = body.decided_by or os.getlogin()
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

    # Append NDJSON event to {run_id}.ndjson for executor signaling
    event_file = events_dir / f"{run_id}.ndjson"
    event = {
        "event_type": "gate.decided",
        "payload": json.dumps({
            "node_name": node_name,
            "decision": "approved",
            "decided_by": decided_by,
            "comment": body.comment,
        }),
        "created_at": decided_at,
    }
    with open(event_file, "a") as f:
        f.write(json.dumps(event) + "\n")

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
    decided_by = body.decided_by or os.getlogin()
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

    # Append NDJSON event to {run_id}.ndjson for executor signaling
    event_file = events_dir / f"{run_id}.ndjson"
    event = {
        "event_type": "gate.decided",
        "payload": json.dumps({
            "node_name": node_name,
            "decision": "rejected",
            "decided_by": decided_by,
            "comment": body.comment,
        }),
        "created_at": decided_at,
    }
    with open(event_file, "a") as f:
        f.write(json.dumps(event) + "\n")

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


@router.post("/workflows/{run_id}/interrupts/{node_name}/resume")
async def resume_interrupt(
    request: Request,
    run_id: str,
    node_name: str,
    body: InterruptResumeRequest,
) -> Dict[str, Any]:
    """Resume an interrupted workflow by injecting a resume value."""
    from dag_executor.checkpoint import CheckpointStore  # type: ignore[import-untyped]
    import yaml

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

    # Get checkpoint_prefix from workflow_definition
    workflow_def_yaml = run["workflow_definition"]
    workflow_def = yaml.safe_load(workflow_def_yaml)
    checkpoint_prefix = workflow_def.get("config", {}).get("checkpoint_prefix")

    if not checkpoint_prefix:
        checkpoint_prefix = checkpoint_dir_fallback or os.path.expanduser(
            "~/.dag-executor/checkpoints"
        )

    # Load interrupt checkpoint to get resume_key
    store = CheckpointStore(checkpoint_prefix)
    interrupt_checkpoint = store.load_interrupt(run["workflow_name"], run_id)

    if not interrupt_checkpoint:
        raise HTTPException(status_code=404, detail="Interrupt checkpoint not found")

    # Save resume values
    resume_values = {interrupt_checkpoint.resume_key: body.resume_value}
    store.save_resume_values(run["workflow_name"], run_id, resume_values)

    # Get decided_by from request body or default to OS user
    decided_by = body.decided_by or os.getlogin()
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

    # Update node status to completed with resume_value in output
    update_node(
        db_path,
        node_id,
        status="completed",
        finished_at=decided_at,
        outputs={
            **(node.get("outputs") or {}),
            "resume_value": body.resume_value,
            "node_type": "interrupt"
        }
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

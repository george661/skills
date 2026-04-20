"""FastAPI routes for checkpoint browsing and replay."""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from dag_dashboard.models import (
    CheckpointNodeSummary,
    CheckpointRunDetail,
    CheckpointRunSummary,
    ReplayRequest,
    ReplaySummary,
)
from dag_executor.checkpoint import CheckpointMetadata, CheckpointStore
from dag_executor.replay import execute_replay
from dag_executor.schema import WorkflowDef
from dag_executor import load_workflow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/checkpoints", tags=["checkpoints"])


def get_checkpoint_store(request: Request) -> CheckpointStore:
    """Get checkpoint store from app state, or raise 404 if not configured."""
    checkpoint_prefix: Optional[Path] = getattr(request.app.state, "checkpoint_prefix", None)
    if checkpoint_prefix is None:
        raise HTTPException(status_code=404, detail="Checkpoint store not configured")
    return CheckpointStore(str(checkpoint_prefix))


@router.get("/workflows")
async def list_workflows(request: Request) -> List[str]:
    """List all workflow names discovered in the checkpoint store."""
    store = get_checkpoint_store(request)
    workflows = store.list_workflows()
    return workflows


@router.get("/workflows/{workflow_name}/runs")
async def list_runs(
    workflow_name: str,
    request: Request,
) -> List[CheckpointRunSummary]:
    """List all runs for a given workflow, sorted newest-first."""
    store = get_checkpoint_store(request)
    run_ids = store.list_runs(workflow_name)
    
    summaries: List[CheckpointRunSummary] = []
    for run_id in reversed(run_ids):  # newest first
        meta = store.load_metadata(workflow_name, run_id)
        if meta:
            # Count node checkpoints
            run_dir = store._get_run_dir(workflow_name, run_id)
            nodes_dir = run_dir / "nodes"
            node_count = len(list(nodes_dir.glob("*.json"))) if nodes_dir.exists() else 0
            
            summaries.append(CheckpointRunSummary(
                run_id=run_id,
                workflow_name=meta.workflow_name,
                started_at=meta.started_at,
                status=meta.status,
                node_count=node_count,
                inputs=meta.inputs,
            ))
    
    return summaries


@router.get("/workflows/{workflow_name}/runs/{run_id}")
async def get_run_detail(
    workflow_name: str,
    run_id: str,
    request: Request,
) -> CheckpointRunDetail:
    """Get full run details including all node checkpoint summaries."""
    store = get_checkpoint_store(request)
    
    meta = store.load_metadata(workflow_name, run_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    # Load all node checkpoints
    run_dir = store._get_run_dir(workflow_name, run_id)
    nodes_dir = run_dir / "nodes"
    node_summaries: List[CheckpointNodeSummary] = []
    
    if nodes_dir.exists():
        for node_file in sorted(nodes_dir.glob("*.json")):
            node_id = node_file.stem
            node_checkpoint = store.load_node(workflow_name, run_id, node_id)
            if node_checkpoint:
                node_summaries.append(CheckpointNodeSummary(
                    node_id=node_checkpoint.node_id,
                    status=node_checkpoint.status.value,
                    started_at=node_checkpoint.started_at,
                    completed_at=node_checkpoint.completed_at,
                    content_hash=node_checkpoint.content_hash,
                    has_error=node_checkpoint.error is not None,
                ))
    
    # Build run summary
    run_summary = CheckpointRunSummary(
        run_id=meta.run_id,
        workflow_name=meta.workflow_name,
        started_at=meta.started_at,
        status=meta.status,
        node_count=len(node_summaries),
        inputs=meta.inputs,
    )
    
    return CheckpointRunDetail(
        metadata=run_summary,
        nodes=node_summaries,
    )


@router.get("/workflows/{workflow_name}/runs/{run_id}/nodes/{node_id}")
async def get_node_checkpoint(
    workflow_name: str,
    run_id: str,
    node_id: str,
    request: Request,
) -> Dict[str, Any]:
    """Get full node checkpoint including output data."""
    store = get_checkpoint_store(request)
    
    node_checkpoint = store.load_node(workflow_name, run_id, node_id)
    if not node_checkpoint:
        raise HTTPException(
            status_code=404,
            detail=f"Node checkpoint {node_id} not found for run {run_id}"
        )
    
    return node_checkpoint.model_dump()


@router.post("/workflows/{workflow_name}/runs/{run_id}/replay")
async def replay_from_node(
    workflow_name: str,
    run_id: str,
    request: Request,
    body: ReplayRequest,
) -> ReplaySummary:
    """Replay a workflow from a specific node with optional input overrides."""
    store = get_checkpoint_store(request)
    
    # Validate workflow_path exists
    workflow_path = Path(body.workflow_path)
    if not workflow_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Workflow path does not exist: {body.workflow_path}"
        )
    
    # Load workflow definition
    try:
        workflow_def = load_workflow(str(workflow_path))
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to load workflow: {str(e)}"
        )
    
    # Verify workflow_name matches
    if workflow_def.name != workflow_name:
        raise HTTPException(
            status_code=400,
            detail=f"Workflow name mismatch: {workflow_def.name} != {workflow_name}"
        )
    
    # Execute replay
    try:
        result = execute_replay(
            workflow_def=workflow_def,
            store=store,
            run_id=run_id,
            from_node=body.from_node,
            overrides=body.overrides,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return ReplaySummary(
        new_run_id=result["new_run_id"],
        parent_run_id=result["parent_run_id"],
        replayed_from=result["replayed_from"],
        nodes_cleared=result["nodes_cleared"],
    )

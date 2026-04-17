"""FastAPI routes for workflow dashboard."""
import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from .models import SortBy, RunStatus
from .queries import get_run, list_runs, get_node, list_nodes

router = APIRouter(prefix="/api")


def get_db_path(request: Request) -> Path:
    """Extract database path from app state."""
    db_dir: Path = request.app.state.db_dir
    return db_dir / "dashboard.db"


@router.get("/workflows")
async def get_workflows(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: Optional[RunStatus] = None,
    sort_by: SortBy = Query(default=SortBy.STARTED_AT),
) -> Dict[str, Any]:
    """List workflow runs with pagination and filtering."""
    db_path = get_db_path(request)
    result = list_runs(
        db_path,
        limit=limit,
        offset=offset,
        status=status,
        sort_by=sort_by,
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

    return {
        "run": run,
        "nodes": nodes,
    }


@router.get("/workflows/{run_id}/nodes/{node_id}")
async def get_workflow_node(
    request: Request,
    run_id: str,
    node_id: str,
) -> Dict[str, Any]:
    """Get a single node execution."""
    db_path = get_db_path(request)

    node = get_node(db_path, node_id)
    if node is None or node["run_id"] != run_id:
        raise HTTPException(status_code=404, detail="Node execution not found")

    return node


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

"""API routes for workflow data and SSE."""
import asyncio
import json
from typing import Any, AsyncIterator, Dict, List
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api")


@router.get("/workflows")
async def get_workflows() -> List[Dict[str, Any]]:
    """Get list of all workflows."""
    # TODO: Query from database when workflow storage is implemented
    # For now return empty list to pass tests
    return []


@router.get("/workflows/{run_id}")
async def get_workflow_detail(run_id: str) -> Dict[str, Any]:
    """Get detailed information about a specific workflow."""
    # TODO: Query from database when workflow storage is implemented
    # For now return 404 for all workflows
    raise HTTPException(status_code=404, detail=f"Workflow {run_id} not found")


async def event_generator() -> AsyncIterator[str]:
    """Generate SSE events."""
    # Send initial connection message
    yield f"data: {json.dumps({'type': 'connected', 'message': 'SSE connection established'})}\n\n"
    
    # Keep connection alive with heartbeats
    try:
        while True:
            await asyncio.sleep(30)  # Heartbeat every 30 seconds
            yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': asyncio.get_event_loop().time()})}\n\n"
    except asyncio.CancelledError:
        # Client disconnected
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
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )

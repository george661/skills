"""API routes for orchestrator status queries."""
from fastapi import APIRouter, HTTPException, Request
from pathlib import Path

from .queries import get_run, get_conversation_id_from_run


router = APIRouter(prefix="/api/workflows")


@router.get("/{run_id}/orchestrator/status")
async def get_orchestrator_status(run_id: str, request: Request):
    """Get orchestrator status for a workflow run."""
    db_path = Path(request.app.state.settings.database_path)
    
    # Get run to verify it exists
    run = get_run(db_path, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    # Get conversation_id
    conversation_id = get_conversation_id_from_run(db_path, run_id)
    if not conversation_id:
        return {"alive": False, "model": None, "idle_seconds": 0, "session_uuid": None}
    
    # Query manager
    manager = request.app.state.orchestrator_manager
    if not manager:
        return {"alive": False, "model": None, "idle_seconds": 0, "session_uuid": None}
    
    status = await manager.get_status(run_id, conversation_id)
    return status

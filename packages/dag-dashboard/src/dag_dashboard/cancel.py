"""Cancel API routes for workflow cancellation."""
import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class CancelResponse(BaseModel):
    """Response for cancel request."""
    run_id: str
    status: str
    message: Optional[str] = None


def create_cancel_router(settings, db_path: Path) -> APIRouter:
    """Create cancel API router.
    
    Args:
        settings: Dashboard settings with events_dir
        db_path: Path to SQLite database
        
    Returns:
        FastAPI router with cancel endpoints
    """
    router = APIRouter()
    events_dir = settings.events_dir if hasattr(settings, 'events_dir') else Path(".dag-events")
    events_dir.mkdir(parents=True, exist_ok=True)

    @router.post("/api/workflows/{run_id}/cancel", response_model=CancelResponse)
    async def cancel_workflow(run_id: str) -> CancelResponse:
        """Cancel a running workflow by writing a marker file.
        
        Returns:
            - 404 if run_id doesn't exist
            - 200 with current status if already terminal (idempotent)
            - 200 with current status if running (marker written)
        """
        # Query run status from database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status FROM workflow_runs WHERE id = ?",
            (run_id,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        
        current_status = row[0]
        
        # Terminal states: completed, failed, cancelled
        terminal_states = {"completed", "failed", "cancelled"}
        
        if current_status in terminal_states:
            # Idempotent: already terminal, return current state without writing marker
            return CancelResponse(
                run_id=run_id,
                status=current_status,
                message=f"Run already in terminal state: {current_status}"
            )
        
        # Write cancel marker atomically
        marker_data = {
            "cancelled_by": "dashboard-ui",
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
        }
        
        marker_path = events_dir / f"{run_id}.cancel"
        with tempfile.NamedTemporaryFile(
            mode='w',
            dir=events_dir,
            delete=False,
            suffix='.tmp'
        ) as tmp_file:
            json.dump(marker_data, tmp_file)
            tmp_path = Path(tmp_file.name)
        
        # Atomic rename
        tmp_path.rename(marker_path)
        
        return CancelResponse(
            run_id=run_id,
            status=current_status,
            message="Cancel marker written"
        )

    return router

"""Cancel API routes for workflow cancellation."""
import sqlite3
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dag_executor.cancel import InvalidRunIdError, validate_run_id, write_cancel_marker  # type: ignore[import-untyped]


class CancelResponse(BaseModel):
    """Response for cancel request."""
    run_id: str
    status: str
    message: Optional[str] = None


def create_cancel_router(settings: Any, db_path: Path) -> APIRouter:
    """Create cancel API router.

    Args:
        settings: Dashboard Settings instance with events_dir attribute.
            Typed as Any to avoid a dag_dashboard.config import cycle at module
            load time; the only attribute read is ``events_dir``.
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
            - 400 if run_id contains path-traversal characters
            - 404 if run_id doesn't exist
            - 200 with current status if already terminal (idempotent)
            - 200 with current status if running (marker written)
        """
        # Reject malformed run_ids before touching the DB or filesystem.
        try:
            validate_run_id(run_id)
        except InvalidRunIdError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Query run status from database
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT status FROM workflow_runs WHERE id = ?",
                (run_id,)
            )
            row = cursor.fetchone()
        finally:
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

        # cancelled_by is currently hardcoded; once the dashboard has auth
        # (separate PRP) this should become the authenticated principal.
        write_cancel_marker(events_dir, run_id, cancelled_by="dashboard-ui")

        return CancelResponse(
            run_id=run_id,
            status=current_status,
            message="Cancel marker written"
        )

    return router

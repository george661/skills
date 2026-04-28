"""Cancel API routes for workflow cancellation."""
import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dag_executor.cancel import InvalidRunIdError, validate_run_id, write_cancel_marker

class CancelResponse(BaseModel):
    """Response for cancel request."""
    run_id: str
    status: str
    message: Optional[str] = None


def create_cancel_router(
    settings: Any,
    db_path: Path,
    reconcile_timeout_s: float = 3.0,
    reconcile_poll_interval_s: float = 0.5,
) -> APIRouter:
    """Create cancel API router.

    Args:
        settings: Dashboard Settings instance with events_dir attribute.
            Typed as Any to avoid a dag_dashboard.config import cycle at module
            load time; the only attribute read is ``events_dir``.
        db_path: Path to SQLite database
        reconcile_timeout_s: How long to wait for a live executor to transition
            the run to ``cancelled`` after the cancel marker is written. If the
            status hasn't changed within this window, the dashboard emits a
            synthetic ``workflow_cancelled`` event so the collector reconciles
            the orphaned row. Tests should pass a small value.
        reconcile_poll_interval_s: Poll interval while waiting for the executor.

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

        # Give a live executor process ~3s to observe the marker and emit its
        # own workflow_cancelled event. The dashboard stays fully detached from
        # the executor — we only *nudge*, never kill. If the status hasn't
        # transitioned, the run is orphaned (executor process is gone or
        # never existed); append a synthetic workflow_cancelled event to the
        # run's JSONL so the existing event collector reconciles the DB. This
        # keeps the executor CLI as the authoritative writer in the live case
        # while still letting operators recover from crashed/abandoned runs.
        reconciled = False
        poll_count = max(
            1, int(reconcile_timeout_s / max(reconcile_poll_interval_s, 0.001))
        )
        for _ in range(poll_count):
            await asyncio.sleep(reconcile_poll_interval_s)
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT status FROM workflow_runs WHERE id = ?", (run_id,)
                ).fetchone()
            if row and row[0] == "cancelled":
                reconciled = True
                break

        if not reconciled:
            # Orphan-reconcile path: emit a synthetic workflow_cancelled event
            # into events_dir/{run_id}.ndjson so event_collector picks it up on
            # the next watchdog tick and flips the row to cancelled. Falling
            # back to JSONL (rather than touching the DB from here) keeps the
            # collector as the single source of truth for run state.
            event_file = events_dir / f"{run_id}.ndjson"
            synthetic_event = {
                "event_type": "workflow_cancelled",
                "workflow_id": run_id,
                "node_id": None,
                "status": "cancelled",
                "duration_ms": None,
                "model": None,
                "dispatch": None,
                "metadata": {
                    "cancelled_by": "dashboard-ui:orphan-reconcile",
                    "reason": "cancel requested; no live executor observed marker within timeout",
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            with event_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(synthetic_event) + "\n")

            return CancelResponse(
                run_id=run_id,
                status="cancelling",
                message="Cancel marker written; orphan-reconcile event emitted",
            )

        return CancelResponse(
            run_id=run_id,
            status="cancelled",
            message="Run cancelled by live executor",
        )

    return router

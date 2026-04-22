"""Retry API routes for workflow retry."""
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dag_executor.cancel import InvalidRunIdError, validate_run_id  # type: ignore[import-untyped]
from .config import Settings


class RetryResponse(BaseModel):
    """Response for retry request."""
    run_id: str
    status: str
    message: Optional[str] = None


def create_retry_router(settings: Settings, db_path: Path) -> APIRouter:
    """Create retry API router.

    Args:
        settings: Dashboard Settings instance with events_dir and workflows_dirs
        db_path: Path to SQLite database

    Returns:
        FastAPI router with retry endpoints
    """
    router = APIRouter()
    events_dir = settings.events_dir
    workflows_dirs = settings.workflows_dirs
    events_dir.mkdir(parents=True, exist_ok=True)

    @router.post("/api/workflows/{run_id}/retry", response_model=RetryResponse)
    async def retry_workflow(run_id: str) -> RetryResponse:
        """Retry a failed workflow by resetting state and spawning executor.

        Returns:
            - 400 if run_id contains path-traversal characters
            - 404 if run_id doesn't exist
            - 409 if run is not in failed state
            - 500 if workflow file is missing
            - 200 with status "resuming" if retry initiated
        """
        # Reject malformed run_ids
        try:
            validate_run_id(run_id)
        except InvalidRunIdError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Query run from database
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(
                """SELECT id, workflow_name, status, workflow_definition 
                   FROM workflow_runs WHERE id = ?""",
                (run_id,)
            )
            row = cursor.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

            current_status = row["status"]
            workflow_name = row["workflow_name"]
            # workflow_definition is in DB but not needed for retry

            # Only allow retry for failed runs
            if current_status != "failed":
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot retry run in state {current_status}"
                )

            # Resolve workflow file (search across all configured dirs)
            workflow_file = None
            for workflows_dir in workflows_dirs:
                candidate = workflows_dir / f"{workflow_name}.yaml"
                if candidate.exists():
                    workflow_file = candidate
                    break

            if not workflow_file:
                raise HTTPException(
                    status_code=500,
                    detail=f"Workflow file {workflow_name}.yaml not found in configured directories"
                )

            # Update workflow_runs: reset to resuming state
            cursor.execute(
                """UPDATE workflow_runs 
                   SET status = ?, finished_at = NULL, error = NULL 
                   WHERE id = ?""",
                ("resuming", run_id)
            )

            # Reset failed and skipped nodes to pending
            cursor.execute(
                """UPDATE node_executions 
                   SET status = ?, finished_at = NULL, error = NULL 
                   WHERE run_id = ? AND status IN (?, ?)""",
                ("pending", run_id, "failed", "skipped")
            )

            conn.commit()
        finally:
            conn.close()

        # Spawn detached subprocess
        child_env = {**os.environ, "DAG_EVENTS_DIR": str(events_dir.resolve())}
        
        subprocess.Popen(
            [
                "dag-exec",
                str(workflow_file),
                "--resume",
                "--run-id", run_id
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(events_dir.parent) if events_dir.parent != Path(".") else None,
            env=child_env,
        )

        return RetryResponse(
            run_id=run_id,
            status="resuming",
            message="Retry initiated"
        )

    return router

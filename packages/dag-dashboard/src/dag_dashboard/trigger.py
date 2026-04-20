"""Webhook trigger endpoint for headless workflow execution."""
import asyncio
import re
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import yaml

from .config import Settings
from .queries import insert_run


class TriggerRequest(BaseModel):
    """Request model for webhook trigger."""
    workflow: str = Field(..., description="Workflow name (no .yaml extension)")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="Workflow inputs")
    source: str = Field(..., description="Trigger source identifier (e.g., 'github-webhook')")


class TriggerResponse(BaseModel):
    """Response model for trigger endpoint."""
    run_id: str


def validate_workflow_path(workflow: str, workflows_dir: Path) -> Path:
    """Validate workflow name and resolve to file path.

    Rejects path traversal attempts and ensures workflow file exists.
    """
    # Reject path traversal characters
    if "/" in workflow or ".." in workflow or "\\" in workflow:
        raise HTTPException(
            status_code=400,
            detail="Invalid workflow name: path separators not allowed"
        )

    # Validate alphanumeric + hyphens only (matching insert_run validation)
    if not re.match(r"^[a-zA-Z0-9-]+$", workflow):
        raise HTTPException(
            status_code=400,
            detail="Invalid workflow name: must contain only alphanumeric characters and hyphens"
        )

    # Resolve workflow file path
    workflow_file = workflows_dir / f"{workflow}.yaml"

    # Ensure resolved path is under workflows_dir (defense in depth)
    try:
        workflow_file = workflow_file.resolve()
        workflow_file.relative_to(workflows_dir.resolve())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid workflow path: must be under workflows directory"
        )

    # Check file exists
    if not workflow_file.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Workflow file not found: {workflow}.yaml"
        )

    return workflow_file


def validate_workflow_inputs(workflow_file: Path, inputs: Dict[str, Any]) -> None:
    """Validate workflow inputs against workflow definition.

    Checks required inputs are present and types match.
    """
    # Parse workflow file
    try:
        with open(workflow_file) as f:
            workflow_def = yaml.safe_load(f)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse workflow file: {str(e)}"
        )

    # Get input definitions
    input_defs = workflow_def.get("inputs", {})

    # Check required inputs
    for input_name, input_def in input_defs.items():
        if isinstance(input_def, dict):
            required = input_def.get("required", False)
            input_type = input_def.get("type", "string")

            if required and input_name not in inputs:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing required input: {input_name}"
                )

            # Validate type if input is provided
            if input_name in inputs:
                value = inputs[input_name]
                if input_type == "string" and not isinstance(value, str):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid type for input '{input_name}': expected string, got {type(value).__name__}"
                    )
                elif input_type == "integer" and not isinstance(value, int):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid type for input '{input_name}': expected integer, got {type(value).__name__}"
                    )
                elif input_type == "boolean" and not isinstance(value, bool):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid type for input '{input_name}': expected boolean, got {type(value).__name__}"
                    )


def create_trigger_router(settings: Settings, db_path: Path) -> APIRouter:
    """Create and configure the trigger API router."""
    router = APIRouter(prefix="/api", tags=["trigger"])
    
    @router.post("/trigger", response_model=TriggerResponse)
    async def trigger_workflow(request: TriggerRequest) -> TriggerResponse:
        """Trigger a workflow execution via webhook."""
        # Validate workflow path and get file
        workflow_file = validate_workflow_path(request.workflow, settings.workflows_dir)

        # Validate inputs against workflow definition
        validate_workflow_inputs(workflow_file, request.inputs)

        # Generate run ID
        run_id = str(uuid4())

        # Get current timestamp
        from datetime import datetime, timezone
        started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Insert run into database with trigger_source
        insert_run(
            db_path=db_path,
            run_id=run_id,
            workflow_name=request.workflow,
            status="pending",
            started_at=started_at,
            inputs=request.inputs,
            trigger_source=request.source
        )
        
        # Spawn dag-executor subprocess (non-blocking)
        # Convert inputs to key=value format
        input_args = [f"{k}={v}" for k, v in request.inputs.items()]
        
        # Spawn the subprocess (detached, survives dashboard restart)
        await asyncio.create_subprocess_exec(
            "dag-exec",
            request.workflow,
            *input_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        return TriggerResponse(run_id=run_id)
    
    return router

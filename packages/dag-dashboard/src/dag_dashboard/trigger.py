"""Webhook trigger endpoint for headless workflow execution."""
import asyncio
import hmac
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
import yaml

from .config import Settings
from .queries import insert_run
from .rate_limit import RateLimiter  # Back-compat re-export


class TriggerRequest(BaseModel):
    """Request model for webhook trigger."""
    workflow: str = Field(..., description="Workflow name (no .yaml extension)")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="Workflow inputs")
    source: str = Field(..., description="Trigger source identifier (e.g., 'github-webhook')")


class TriggerResponse(BaseModel):
    """Response model for trigger endpoint."""
    run_id: str


def verify_hmac_signature(request: Request, body: bytes, secret: str) -> None:
    """Verify HMAC-SHA256 signature from X-Hub-Signature-256 header.

    Raises HTTPException(401) if signature is missing or invalid.
    """
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        raise HTTPException(
            status_code=401,
            detail="Missing X-Hub-Signature-256 header"
        )

    # Parse signature format: "sha256=<hex-digest>"
    if not signature_header.startswith("sha256="):
        raise HTTPException(
            status_code=401,
            detail="Invalid signature format: expected sha256=<hex-digest>"
        )

    received_signature = signature_header[7:]  # Strip "sha256=" prefix

    # Compute expected signature
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256
    ).hexdigest()

    # Use constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(received_signature, expected_signature):
        raise HTTPException(
            status_code=401,
            detail="Invalid HMAC signature"
        )


def validate_workflow_path(workflow: str, workflows_dir: Path) -> Path:
    """Validate workflow name and resolve to file path.

    Rejects path traversal attempts and ensures workflow file exists.
    """
    # Reject path traversal characters and dots (prevents .yaml.yaml issue)
    if "/" in workflow or ".." in workflow or "\\" in workflow or "." in workflow:
        raise HTTPException(
            status_code=400,
            detail="Invalid workflow name: path separators and dots not allowed"
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

    Uses dag_executor.parser to parse workflow and Pydantic validation.
    """
    try:
        from dag_executor.parser import load_workflow  # type: ignore[import-untyped]
        from pydantic import ValidationError
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to import dag_executor parser: {str(e)}"
        )

    # Parse workflow file using dag_executor parser
    try:
        workflow_def = load_workflow(str(workflow_file))
    except (FileNotFoundError, ValueError, ValidationError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse workflow file: {str(e)}"
        )

    # Validate inputs using the parsed workflow definition
    if workflow_def.inputs:
        for input_name, input_def in workflow_def.inputs.items():
            # Check required inputs
            if input_def.required and input_name not in inputs:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing required input: {input_name}"
                )

            # Validate type if input is provided
            if input_name in inputs:
                value = inputs[input_name]
                expected_type = input_def.type

                # Validate type based on YAML type
                if expected_type == "string" and not isinstance(value, str):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid type for input '{input_name}': expected string, got {type(value).__name__}"
                    )
                elif expected_type == "integer" and not isinstance(value, int):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid type for input '{input_name}': expected integer, got {type(value).__name__}"
                    )
                elif expected_type == "number" and not isinstance(value, (int, float)):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid type for input '{input_name}': expected number, got {type(value).__name__}"
                    )
                elif expected_type == "boolean" and not isinstance(value, bool):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid type for input '{input_name}': expected boolean, got {type(value).__name__}"
                    )

                # Validate pattern if specified
                if input_def.pattern and isinstance(value, str):
                    if not re.match(input_def.pattern, value):
                        raise HTTPException(
                            status_code=400,
                            detail=f"Input '{input_name}' does not match pattern: {input_def.pattern}"
                        )


def create_trigger_router(settings: Settings, db_path: Path) -> APIRouter:
    """Create and configure the trigger API router."""
    router = APIRouter(prefix="/api", tags=["trigger"])

    # Initialize rate limiter
    rate_limiter = RateLimiter(settings.trigger_rate_limit_per_min)

    @router.post("/trigger", response_model=TriggerResponse)
    async def trigger_workflow(request_body: TriggerRequest, request: Request) -> TriggerResponse:
        """Trigger a workflow execution via webhook."""
        # HMAC verification (if secret is configured)
        if settings.trigger_secret:
            body_bytes = await request.body()
            verify_hmac_signature(request, body_bytes, settings.trigger_secret)

        # Rate limiting
        if not rate_limiter.is_allowed(request_body.source):
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for source '{request_body.source}'"
            )

        # Validate workflow path and get file
        workflow_file = validate_workflow_path(request_body.workflow, settings.workflows_dir)

        # Validate inputs against workflow definition
        validate_workflow_inputs(workflow_file, request_body.inputs)

        # Generate run ID
        run_id = str(uuid4())

        # Get current timestamp
        from datetime import datetime, timezone
        started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Insert run into database with trigger_source
        insert_run(
            db_path=db_path,
            run_id=run_id,
            workflow_name=request_body.workflow,
            status="pending",
            started_at=started_at,
            inputs=request_body.inputs,
            trigger_source=request_body.source
        )

        # Spawn dag-executor subprocess (non-blocking)
        # Convert inputs to key=value format, serialize non-scalar values as JSON
        input_args = []
        for k, v in request_body.inputs.items():
            if isinstance(v, (dict, list)):
                # Serialize complex values as JSON
                input_args.append(f"{k}={json.dumps(v)}")
            else:
                # Keep scalars as-is
                input_args.append(f"{k}={v}")

        # Pass events_dir to the executor via DAG_EVENTS_DIR so it writes
        # NDJSON events at {events_dir}/{run_id}.ndjson (where the collector
        # watches) and polls {events_dir}/{run_id}.cancel for cancel markers.
        child_env = {**os.environ, "DAG_EVENTS_DIR": str(settings.events_dir.resolve())}

        # Spawn the subprocess (detached, survives dashboard restart).
        # CRITICAL: Pass --run-id so the executor uses the same run_id we
        # INSERTed into workflow_runs above. Otherwise it generates a new
        # UUID and emits events under a run_id the DB row does not know.
        await asyncio.create_subprocess_exec(
            "dag-exec",
            str(workflow_file),  # Pass resolved file path, not workflow name
            "--run-id", run_id,
            *input_args,
            stdout=asyncio.subprocess.DEVNULL,  # Avoid pipe leak
            stderr=asyncio.subprocess.DEVNULL,  # Avoid pipe leak
            cwd=str(settings.events_dir.parent) if settings.events_dir.parent != Path(".") else None,
            env=child_env,
        )

        return TriggerResponse(run_id=run_id)

    return router

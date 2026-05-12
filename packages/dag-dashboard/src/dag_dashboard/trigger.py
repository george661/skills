"""Webhook trigger endpoint for headless workflow execution."""
import asyncio
import hmac
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
import yaml

from .config import Settings
from .queries import get_conversation_row, insert_conversation, insert_run
from .rate_limit import RateLimiter  # Back-compat re-export


class TriggerRequest(BaseModel):
    """Request model for webhook trigger."""
    workflow: str = Field(..., description="Workflow name (no .yaml extension)")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="Workflow inputs")
    source: str = Field(..., description="Trigger source identifier (e.g., 'github-webhook')")
    model_override: Optional[Literal["opus", "sonnet", "local"]] = Field(
        default=None,
        description="Override model tier for all prompt nodes (unless strict_model=true)"
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional existing conversation ID to continue. Must reference an "
            "existing row in `conversations`. When omitted a fresh conversation "
            "is minted per run so the orchestrator chat (GW-5492) is reachable."
        ),
    )


class TriggerResponse(BaseModel):
    """Response model for trigger endpoint."""
    run_id: str
    conversation_id: str


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


def validate_workflow_path(workflow: str, workflows_dirs: List[Path]) -> Path:
    """Validate workflow name and resolve to file path.

    Searches across multiple workflows directories (first match wins).
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

    # Search for workflow file across configured directories (first match wins)
    for workflows_dir in workflows_dirs:
        workflow_file = workflows_dir / f"{workflow}.yaml"
        if workflow_file.exists():
            # Found it - validate and return
            break
    else:
        # Not found in any directory
        raise HTTPException(
            status_code=400,
            detail=f"Workflow '{workflow}' not found in configured directories"
        )

    # Ensure resolved path is under its source workflows_dir (defense in depth)
    try:
        workflow_file = workflow_file.resolve()
        workflow_file.relative_to(workflows_dir.resolve())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid workflow path: must be under workflows directory"
        )

    return workflow_file


def validate_workflow_inputs(workflow_file: Path, inputs: Dict[str, Any]) -> None:
    """Validate workflow inputs against workflow definition.

    Uses dag_executor.parser to parse workflow and Pydantic validation.
    """
    try:
        from dag_executor.parser import load_workflow
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
        # Runtime gate: when operator disables trigger via Settings UI the
        # router stays mounted (so re-enabling does not need a restart) but
        # the endpoint returns 404 exactly like an unmounted route would.
        if not settings.trigger_enabled:
            raise HTTPException(status_code=404, detail="Not Found")

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
        workflow_file = validate_workflow_path(request_body.workflow, settings.workflows_dirs)

        # Validate inputs against workflow definition
        validate_workflow_inputs(workflow_file, request_body.inputs)

        # Generate run ID
        run_id = str(uuid4())

        # Get current timestamp
        from datetime import datetime, timezone
        started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Resolve conversation: reuse if the caller supplied a known id, otherwise
        # mint a fresh one. This is what wires the run to the GW-5492 orchestrator —
        # without a conversation_id on workflow_runs, chat_routes.py skips
        # orchestrator_manager.route_message and the chat never reaches the LLM.
        if request_body.conversation_id:
            existing = get_conversation_row(db_path, request_body.conversation_id)
            if not existing:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Unknown conversation_id '{request_body.conversation_id}'. "
                        "Omit the field to mint a new conversation."
                    ),
                )
            conversation_id = request_body.conversation_id
        else:
            conversation_id = str(uuid4())
            insert_conversation(
                db_path=db_path,
                conversation_id=conversation_id,
                origin="dashboard",
                created_at=started_at,
            )

        # Insert run into database with trigger_source and conversation_id
        insert_run(
            db_path=db_path,
            run_id=run_id,
            workflow_name=request_body.workflow,
            status="pending",
            started_at=started_at,
            inputs=request_body.inputs,
            trigger_source=request_body.source,
            conversation_id=conversation_id,
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

        # Build dag-exec command. Invoke via `sys.executable -m dag_executor`
        # rather than the `dag-exec` console script so the subprocess runs
        # under the same interpreter as the dashboard — no dependence on
        # PATH lookup. Without this, a stale `dag-exec` shim from a system
        # Python (e.g. miniconda) earlier on PATH would execute but
        # ModuleNotFoundError on dag_executor, silently failing the run.
        # --conversation + --db enable the executor's session-continuity
        # path (see executor.py:_get_or_mint_session) so prompt nodes can
        # resume a single Claude session across the run and the
        # orchestrator chat can join the same conversation.
        dag_exec_args = [
            sys.executable,
            "-m", "dag_executor",
            str(workflow_file),  # Pass resolved file path, not workflow name
            "--run-id", run_id,
            "--conversation", conversation_id,
            "--db", str(db_path),
        ]

        # Add model override if provided
        if request_body.model_override:
            dag_exec_args.extend(["--model-override", request_body.model_override])

        dag_exec_args.extend(input_args)

        # Spawn the subprocess (detached, survives dashboard restart).
        # CRITICAL: Pass --run-id so the executor uses the same run_id we
        # INSERTed into workflow_runs above. Otherwise it generates a new
        # UUID and emits events under a run_id the DB row does not know.
        #
        # Redirect subprocess stderr/stdout to a per-run log file under
        # events_dir so crashes (import errors, CLI arg errors, unhandled
        # exceptions) are observable after the fact. Previously /dev/null
        # meant "run stays pending forever" with zero diagnostic signal.
        log_path = settings.events_dir.resolve() / f"{run_id}.subprocess.log"
        log_handle = open(log_path, "wb")  # noqa: SIM115 — handle closed by subprocess lifecycle
        try:
            await asyncio.create_subprocess_exec(
                *dag_exec_args,
                stdout=log_handle,
                stderr=log_handle,
                cwd=str(settings.events_dir.parent) if settings.events_dir.parent != Path(".") else None,
                env=child_env,
            )
        finally:
            # The subprocess inherits the fd; we can close our handle.
            log_handle.close()

        return TriggerResponse(run_id=run_id, conversation_id=conversation_id)

    return router

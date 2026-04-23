"""FastAPI routes for workflow draft management."""
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from dag_dashboard.definitions import WORKFLOW_NAME_PATTERN
from dag_dashboard.models import (
    CurrentDraftResponse,
    CurrentDraftUpdateRequest,
    DraftCreateRequest,
    DraftCreateResponse,
    DraftListItem,
    DraftPublishResponse,
    DraftUpdateRequest,
)
from dag_executor.parser import load_workflow_from_string

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["drafts"])

# Timestamp format: YYYYMMDDTHHMMSS_uuuuuuZ (UTC with microseconds, sortable)
TIMESTAMP_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}_[0-9]{6}Z$")


def _validate_workflow_name(name: str) -> None:
    """Validate workflow name matches pattern (alphanumeric + hyphens only).
    
    Raises:
        HTTPException: 400 if name is invalid
    """
    if not WORKFLOW_NAME_PATTERN.match(name):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid workflow name: {name}. Only alphanumeric characters and hyphens are allowed."
        )


def _validate_timestamp(timestamp: str) -> None:
    """Validate timestamp format.
    
    Raises:
        HTTPException: 400 if timestamp is invalid
    """
    if not TIMESTAMP_PATTERN.match(timestamp):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timestamp format: {timestamp}. Expected YYYYMMDDTHHMMSS_uuuuuuZ."
        )


def _resolve_draft(
    workflows_dirs: List[Path], name: str, timestamp: str
) -> Tuple[Path, Path]:
    """Find draft file across multiple directories.
    
    Args:
        workflows_dirs: List of workflow directories to search
        name: Workflow name
        timestamp: Draft timestamp
        
    Returns:
        Tuple of (draft_path, workflows_dir) where draft was found
        
    Raises:
        HTTPException: 404 if draft not found
    """
    for workflows_dir in workflows_dirs:
        draft_path = workflows_dir / ".drafts" / name / f"{timestamp}.yaml"
        if draft_path.exists():
            return draft_path, workflows_dir
    
    raise HTTPException(
        status_code=404,
        detail=f"Draft {timestamp} not found for workflow {name}"
    )


def _primary_workflows_dir(workflows_dirs: List[Path]) -> Path:
    """Get the primary (first) workflows directory for writes.
    
    Returns:
        First workflows_dir (creates if missing)
    """
    if not workflows_dirs:
        raise HTTPException(
            status_code=500,
            detail="No workflows directories configured"
        )
    
    primary = workflows_dirs[0]
    primary.mkdir(parents=True, exist_ok=True)
    return primary


def _prune_drafts(drafts_dir: Path, keep: int = 50) -> None:
    """Delete oldest drafts if count exceeds limit.

    Args:
        drafts_dir: Directory containing draft files
        keep: Maximum number of drafts to keep
    """
    draft_files = sorted(drafts_dir.glob("*.yaml"))
    if len(draft_files) > keep:
        to_delete = draft_files[: len(draft_files) - keep]
        for draft_file in to_delete:
            draft_file.unlink()
            logger.info(f"Pruned old draft: {draft_file}")


def _resolve_current_pointer(
    workflows_dirs: List[Path], name: str
) -> Tuple[Path, Path]:
    """Find .current pointer file across multiple directories.

    Args:
        workflows_dirs: List of workflow directories to search
        name: Workflow name

    Returns:
        Tuple of (current_path, workflows_dir) where .current was found

    Raises:
        HTTPException: 404 if .current not found
    """
    for workflows_dir in workflows_dirs:
        current_path = workflows_dir / ".drafts" / name / ".current"
        if current_path.exists():
            return current_path, workflows_dir

    raise HTTPException(
        status_code=404,
        detail=f"No current draft pointer found for workflow {name}"
    )


def _write_current_pointer(
    workflows_dir: Path, name: str, timestamp: str
) -> None:
    """Write .current pointer file atomically.

    Args:
        workflows_dir: Workflows directory (primary)
        name: Workflow name
        timestamp: Draft timestamp to point to
    """
    drafts_dir = workflows_dir / ".drafts" / name
    drafts_dir.mkdir(parents=True, exist_ok=True)
    current_path = drafts_dir / ".current"

    # Use tempfile + os.replace for atomic write
    with tempfile.NamedTemporaryFile(
        mode='w',
        delete=False,
        dir=drafts_dir,
        prefix=".tmp-current-",
        suffix=""
    ) as tmp:
        tmp_path = Path(tmp.name)

    try:
        tmp_path.write_text(timestamp)
        os.replace(str(tmp_path), str(current_path))
        logger.info(f"Updated .current pointer for {name} to {timestamp}")
    except Exception:
        # Clean up temp file on error
        if tmp_path.exists():
            tmp_path.unlink()
        raise


@router.get("/{name}/drafts")
async def list_drafts(name: str, request: Request) -> List[DraftListItem]:
    """List all drafts for a workflow, newest first.
    
    Returns:
        List of draft items with timestamp and size
    """
    _validate_workflow_name(name)
    
    workflows_dirs: List[Path] = request.app.state.workflows_dirs
    
    # Collect drafts across all directories
    drafts: List[DraftListItem] = []
    seen_timestamps = set()
    
    for workflows_dir in workflows_dirs:
        drafts_dir = workflows_dir / ".drafts" / name
        if not drafts_dir.exists():
            continue
        
        for draft_file in drafts_dir.glob("*.yaml"):
            timestamp = draft_file.stem
            
            # Skip if already seen (first-dir-wins)
            if timestamp in seen_timestamps:
                continue
            
            seen_timestamps.add(timestamp)
            drafts.append(
                DraftListItem(
                    timestamp=timestamp,
                    size_bytes=draft_file.stat().st_size,
                )
            )
    
    # Sort newest first
    drafts.sort(key=lambda d: d.timestamp, reverse=True)
    return drafts


@router.get("/{name}/drafts/current")
async def get_current_draft_pointer(
    name: str, request: Request
) -> CurrentDraftResponse:
    """Get the current draft pointer timestamp.

    Returns:
        Response with timestamp of the current draft

    Raises:
        HTTPException: 404 if no .current pointer exists
    """
    _validate_workflow_name(name)

    workflows_dirs: List[Path] = request.app.state.workflows_dirs
    current_path, _ = _resolve_current_pointer(workflows_dirs, name)

    timestamp = current_path.read_text().strip()
    return CurrentDraftResponse(timestamp=timestamp)


@router.put("/{name}/drafts/current", status_code=204)
async def update_current_draft_pointer(
    name: str, body: CurrentDraftUpdateRequest, request: Request
) -> None:
    """Update the current draft pointer to a specific timestamp.

    Args:
        name: Workflow name
        body: Request with timestamp to point to

    Raises:
        HTTPException: 400 if timestamp format invalid
        HTTPException: 404 if referenced draft doesn't exist
    """
    _validate_workflow_name(name)
    _validate_timestamp(body.timestamp)

    workflows_dirs: List[Path] = request.app.state.workflows_dirs

    # Verify the draft exists before setting pointer
    _ = _resolve_draft(workflows_dirs, name, body.timestamp)

    # Write pointer to primary directory
    primary = _primary_workflows_dir(workflows_dirs)
    _write_current_pointer(primary, name, body.timestamp)


@router.get("/{name}/drafts/{timestamp}")
async def get_draft(
    name: str, timestamp: str, request: Request
) -> Dict[str, Any]:
    """Get draft content and parsed YAML.

    Returns 200 with parsed=null on YAML errors (intentionally lenient to allow
    operators to retrieve and fix broken drafts), unlike publish which returns 400.

    Returns:
        Dict with timestamp, content (raw YAML), and parsed data
    """
    _validate_workflow_name(name)
    _validate_timestamp(timestamp)
    
    workflows_dirs: List[Path] = request.app.state.workflows_dirs
    draft_path, _ = _resolve_draft(workflows_dirs, name, timestamp)
    
    # Read content
    content = draft_path.read_text()
    
    # Parse YAML
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as e:
        logger.warning(f"Failed to parse draft YAML: {e}")
        parsed = None
    
    return {
        "timestamp": timestamp,
        "content": content,
        "parsed": parsed,
    }


@router.post("/{name}/drafts", status_code=201)
async def create_draft(
    name: str, body: DraftCreateRequest, request: Request
) -> DraftCreateResponse:
    """Create a new draft with generated timestamp.
    
    Returns:
        Response with generated timestamp
    """
    _validate_workflow_name(name)
    
    workflows_dirs: List[Path] = request.app.state.workflows_dirs
    primary_dir = _primary_workflows_dir(workflows_dirs)
    
    # Create drafts directory
    drafts_dir = primary_dir / ".drafts" / name
    drafts_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate timestamp with microsecond precision and collision protection
    # Keep regenerating with fresh timestamps until we get a unique one
    while True:
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%dT%H%M%S_%fZ")
        draft_path = drafts_dir / f"{timestamp}.yaml"
        if not draft_path.exists():
            break

    # Write draft
    draft_path.write_text(body.content)
    
    logger.info(f"Created draft: {draft_path}")
    
    # Prune old drafts
    _prune_drafts(drafts_dir, keep=50)
    
    return DraftCreateResponse(timestamp=timestamp)


@router.put("/{name}/drafts/{timestamp}", status_code=204)
async def update_draft(
    name: str, timestamp: str, body: DraftUpdateRequest, request: Request
) -> None:
    """Update draft in place (autosave)."""
    _validate_workflow_name(name)
    _validate_timestamp(timestamp)
    
    workflows_dirs: List[Path] = request.app.state.workflows_dirs
    draft_path, _ = _resolve_draft(workflows_dirs, name, timestamp)
    
    # Overwrite content
    draft_path.write_text(body.content)
    logger.info(f"Updated draft: {draft_path}")


@router.delete("/{name}/drafts/{timestamp}", status_code=204)
async def delete_draft(name: str, timestamp: str, request: Request) -> None:
    """Delete a draft."""
    _validate_workflow_name(name)
    _validate_timestamp(timestamp)
    
    workflows_dirs: List[Path] = request.app.state.workflows_dirs
    draft_path, _ = _resolve_draft(workflows_dirs, name, timestamp)
    
    # Remove file
    draft_path.unlink()
    logger.info(f"Deleted draft: {draft_path}")


@router.post("/{name}/drafts/{timestamp}/publish")
async def publish_draft(
    name: str, timestamp: str, request: Request
) -> DraftPublishResponse:
    """Publish draft as canonical workflow file.
    
    Validates schema before atomic rename.
    
    Returns:
        Response with published path and source timestamp
    """
    _validate_workflow_name(name)
    _validate_timestamp(timestamp)
    
    workflows_dirs: List[Path] = request.app.state.workflows_dirs
    draft_path, workflows_dir = _resolve_draft(workflows_dirs, name, timestamp)
    
    # Read content
    content = draft_path.read_text()
    
    # Validate schema (catches both YAML syntax and schema errors)
    try:
        load_workflow_from_string(content)
    except ValueError as e:
        # YAML syntax error
        raise HTTPException(
            status_code=400,
            detail=f"Invalid YAML syntax: {e}"
        )
    except ValidationError as e:
        # Pydantic schema validation error
        raise HTTPException(
            status_code=400,
            detail=f"Schema validation failed: {e}"
        )
    
    # Write to temporary file in same directory (for atomic rename)
    canonical_path = workflows_dir / f"{name}.yaml"

    # Use tempfile for collision-proof tmp name
    with tempfile.NamedTemporaryFile(
        mode='w',
        delete=False,
        dir=workflows_dir,
        prefix=f".tmp-{name}-",
        suffix=".yaml"
    ) as tmp:
        tmp_path = Path(tmp.name)

    try:
        # Write content
        tmp_path.write_text(content)

        # Atomic rename (POSIX)
        os.replace(str(tmp_path), str(canonical_path))

        logger.info(f"Published draft {timestamp} to {canonical_path}")

        return DraftPublishResponse(
            published_path=str(canonical_path),
            source_timestamp=timestamp,
        )
    finally:
        # Cleanup tmp file if rename failed
        if tmp_path.exists():
            tmp_path.unlink()

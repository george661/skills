"""FastAPI routes for workflow draft management."""
import difflib
import logging
import os
import re
import socket
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
    DraftDiffRequest,
    DraftDiffResponse,
    DraftListItem,
    DraftPublishResponse,
    DraftUpdateRequest,
)
from dag_executor.parser import load_workflow_from_string
from dag_executor.drafts_fs import (
    list_drafts as fs_list_drafts,
    read_draft as fs_read_draft,
    publish as fs_publish,
    delete_draft as fs_delete_draft,
    prune as fs_prune,
)

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


def _prune_drafts(workflows_dir: Path, name: str, keep: int = 50) -> None:
    """Delete oldest drafts if count exceeds limit.

    Delegates to drafts_fs.prune.

    Args:
        workflows_dir: Base workflows directory
        name: Workflow name
        keep: Maximum number of drafts to keep
    """
    fs_prune(workflows_dir, name, keep=keep)


def _read_publishers_from_log(drafts_dir: Path) -> Dict[str, str]:
    """Read PUBLISHED.log and return dict mapping draft timestamp to publisher.

    Format: YYYY-MM-DDTHH:MM:SSZ  {publisher}  published {draft_timestamp}
    (two-space separators)

    Args:
        drafts_dir: Directory containing PUBLISHED.log

    Returns:
        Dict mapping draft timestamp to publisher email
    """
    published_log = drafts_dir / "PUBLISHED.log"
    if not published_log.exists():
        return {}

    publishers: Dict[str, str] = {}
    try:
        content = published_log.read_text()
        for line in content.strip().split("\n"):
            if not line:
                continue
            # Parse format: timestamp  publisher  published draft_ts
            parts = line.split("  ")  # two-space separator
            if len(parts) >= 3 and parts[2].startswith("published "):
                draft_ts = parts[2].replace("published ", "")
                publisher = parts[1]
                publishers[draft_ts] = publisher
    except Exception as e:
        logger.warning(f"Failed to parse PUBLISHED.log: {e}")
        return {}

    return publishers


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

    Delegates to drafts_fs.list_drafts for each directory, then merges with
    first-dir-wins semantics and reverse-sorts (newest first).

    Returns:
        List of draft items with timestamp, size, and publisher
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

        # Delegate to drafts_fs.list_drafts to get timestamps
        timestamps = fs_list_drafts(workflows_dir, name)

        # Read PUBLISHED.log once per directory
        publishers = _read_publishers_from_log(drafts_dir)

        for timestamp in timestamps:
            # Skip if already seen (first-dir-wins)
            if timestamp in seen_timestamps:
                continue

            seen_timestamps.add(timestamp)

            # Stat the file for size
            draft_file = drafts_dir / f"{timestamp}.yaml"
            size_bytes = draft_file.stat().st_size if draft_file.exists() else 0

            drafts.append(
                DraftListItem(
                    timestamp=timestamp,
                    size_bytes=size_bytes,
                    publisher=publishers.get(timestamp),
                )
            )

    # Sort newest first (preserve reverse-sort semantics)
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

    Delegates to drafts_fs.read_draft for content retrieval.

    Returns 200 with parsed=null on YAML errors (intentionally lenient to allow
    operators to retrieve and fix broken drafts), unlike publish which returns 400.

    Returns:
        Dict with timestamp, content (raw YAML), and parsed data
    """
    _validate_workflow_name(name)
    _validate_timestamp(timestamp)

    workflows_dirs: List[Path] = request.app.state.workflows_dirs

    # Resolve which workflows_dir contains the draft (multi-dir support)
    _, workflows_dir = _resolve_draft(workflows_dirs, name, timestamp)

    # Delegate to drafts_fs.read_draft
    try:
        content = fs_read_draft(workflows_dir, name, timestamp)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Draft not found")

    # Parse YAML (lenient - return parsed=null on error)
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

    TODO(GW-5331): Migrate to drafts_fs.write_draft once format is normalized.
    For now: keep inline to preserve existing 23-char microsecond format.

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

    # Prune old drafts - delegate to drafts_fs.prune
    _prune_drafts(primary_dir, name, keep=50)

    return DraftCreateResponse(timestamp=timestamp)


@router.put("/{name}/drafts/{timestamp}", status_code=204)
async def update_draft(
    name: str, timestamp: str, body: DraftUpdateRequest, request: Request
) -> None:
    """Update draft in place (autosave).

    TODO: Move to drafts_fs.update_draft when added (out of scope for this PR).
    For now: keep inline atomic in-place overwrite.
    """
    _validate_workflow_name(name)
    _validate_timestamp(timestamp)

    workflows_dirs: List[Path] = request.app.state.workflows_dirs
    draft_path, _ = _resolve_draft(workflows_dirs, name, timestamp)

    # Overwrite content
    draft_path.write_text(body.content)
    logger.info(f"Updated draft: {draft_path}")


@router.delete("/{name}/drafts/{timestamp}", status_code=204)
async def delete_draft(name: str, timestamp: str, request: Request) -> None:
    """Delete a draft.

    Delegates to drafts_fs.delete_draft for idempotent deletion.
    """
    _validate_workflow_name(name)
    _validate_timestamp(timestamp)

    workflows_dirs: List[Path] = request.app.state.workflows_dirs

    # Resolve which workflows_dir contains the draft (404 if missing)
    _, workflows_dir = _resolve_draft(workflows_dirs, name, timestamp)

    # Delegate to drafts_fs.delete_draft (idempotent)
    fs_delete_draft(workflows_dir, name, timestamp)
    logger.info(f"Deleted draft {name}/{timestamp}")


@router.post("/{name}/drafts/{timestamp}/publish")
async def publish_draft(
    name: str, timestamp: str, request: Request
) -> DraftPublishResponse:
    """Publish draft as canonical workflow file.

    Validates schema before atomic rename.
    Delegates to drafts_fs.publish for atomic rename + PUBLISHED.log audit trail.

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
    # This is the REST boundary responsibility - validate before publishing
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

    # Derive publisher identity (single-token, colon-delimited format)
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown"
    host = socket.gethostname()
    publisher = f"dashboard-ui:{user}@{host}"

    # Delegate to drafts_fs.publish for atomic rename + PUBLISHED.log append
    # This ensures dashboard publish writes the same audit trail as CLI publish
    fs_publish(workflows_dir, name, timestamp, publisher)

    canonical_path = workflows_dir / f"{name}.yaml"
    logger.info(f"Published draft {timestamp} to {canonical_path} by {publisher}")

    return DraftPublishResponse(
        published_path=str(canonical_path),
        source_timestamp=timestamp,
    )


@router.post("/{name}/drafts/diff")
async def diff_drafts(
    name: str, request: Request, body: DraftDiffRequest
) -> DraftDiffResponse:
    """Get unified diff between a draft and provided content.

    Args:
        name: Workflow name
        body: Request with from_ts (draft timestamp) and to_content (current content)

    Returns:
        Unified diff and first change line summary
    """
    _validate_workflow_name(name)
    _validate_timestamp(body.from_ts)

    workflows_dirs: List[Path] = request.app.state.workflows_dirs
    draft_path, _ = _resolve_draft(workflows_dirs, name, body.from_ts)

    # Read draft content
    from_content = draft_path.read_text()

    # Generate unified diff
    from_lines = from_content.splitlines(keepends=True)
    to_lines = body.to_content.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            from_lines,
            to_lines,
            fromfile=f"draft ({body.from_ts})",
            tofile="current canvas",
            lineterm="",
        )
    )

    unified_diff = "\n".join(diff_lines)

    # Extract first change line (first line starting with + or -)
    first_change_line = ""
    for line in diff_lines:
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            first_change_line = line.strip()
            break

    return DraftDiffResponse(
        unified_diff=unified_diff,
        first_change_line=first_change_line,
    )

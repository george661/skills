"""Shared filesystem module for workflow draft management.

This module provides atomic file operations for managing workflow drafts,
supporting both the dashboard REST API and the CLI. Drafts are stored in
a .drafts/{workflow_name}/ directory structure.

Path-traversal defense is the responsibility of callers (REST layer).
This module trusts the workflow name parameter.

All timestamp operations use UTC timezone and format YYYYMMDDTHHMMSSZ
(basic ISO-8601, no colons) for filesystem compatibility.
"""

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List


# Constants
KEEP_DEFAULT = 50
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
LOG_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
FILE_MODE = 0o644
DIR_MODE = 0o755


def _drafts_dir(workflow_dir: Path, name: str) -> Path:
    """Return path to drafts directory for a workflow."""
    return workflow_dir / ".drafts" / name


def _draft_path(workflow_dir: Path, name: str, ts: str) -> Path:
    """Return path to a specific draft file."""
    return _drafts_dir(workflow_dir, name) / f"{ts}.yaml"


def _published_log_path(workflow_dir: Path, name: str) -> Path:
    """Return path to PUBLISHED.log file."""
    return _drafts_dir(workflow_dir, name) / "PUBLISHED.log"


def _canonical_path(workflow_dir: Path, name: str) -> Path:
    """Return path to canonical workflow file."""
    return workflow_dir / f"{name}.yaml"


def list_drafts(workflow_dir: Path, name: str) -> List[str]:
    """Return draft timestamps sorted oldest→newest.
    
    Returns [] if no drafts directory exists. Excludes PUBLISHED.log
    and dotfiles (.current, .gitignore, etc.).
    
    Args:
        workflow_dir: Base directory containing workflows
        name: Workflow name
        
    Returns:
        List of timestamp strings in YYYYMMDDTHHMMSSZ format, sorted oldest first
    """
    drafts_path = _drafts_dir(workflow_dir, name)
    if not drafts_path.exists():
        return []
    
    # Get all .yaml files, extract timestamps, filter dotfiles and log
    drafts = []
    for item in drafts_path.iterdir():
        if item.is_file() and item.suffix == ".yaml":
            # Exclude files starting with dot
            if not item.stem.startswith("."):
                drafts.append(item.stem)
    
    # Sort oldest first (lexicographic sort works with YYYYMMDDTHHMMSSZ format)
    return sorted(drafts)


def read_draft(workflow_dir: Path, name: str, ts: str) -> str:
    """Return YAML text of the named draft.
    
    Args:
        workflow_dir: Base directory containing workflows
        name: Workflow name
        ts: Timestamp string in YYYYMMDDTHHMMSSZ format
        
    Returns:
        YAML content as string
        
    Raises:
        FileNotFoundError: If the draft does not exist
    """
    draft_file = _draft_path(workflow_dir, name, ts)
    return draft_file.read_text()


def write_draft(workflow_dir: Path, name: str, yaml_text: str) -> str:
    """Atomically write a new draft.
    
    Creates .drafts/{name}/ directory on first call with 0o755 permissions.
    Uses atomic temp-then-rename pattern for write safety.
    
    Does NOT auto-prune — caller must explicitly call prune() if desired.
    
    Args:
        workflow_dir: Base directory containing workflows
        name: Workflow name
        yaml_text: YAML content to write
        
    Returns:
        Filename-safe timestamp string (YYYYMMDDTHHMMSSZ) used as draft ID
        
    Raises:
        RuntimeError: If timestamp collision persists after 1s of retries
    """
    # Ensure drafts directory exists with correct permissions
    drafts_path = _drafts_dir(workflow_dir, name)
    drafts_path.mkdir(parents=True, mode=DIR_MODE, exist_ok=True)
    
    # Generate timestamp with collision handling
    max_retries = 100  # 100 * 0.01s = 1s max wait
    for attempt in range(max_retries):
        ts = datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)
        draft_file = _draft_path(workflow_dir, name, ts)
        
        if not draft_file.exists():
            # Atomic write: temp file then rename
            temp_file = draft_file.with_suffix('.yaml.tmp')
            temp_file.write_text(yaml_text)
            os.chmod(temp_file, FILE_MODE)
            temp_file.replace(draft_file)
            return ts
        
        # Collision detected, wait and retry
        if attempt < max_retries - 1:
            time.sleep(0.01)
    
    raise RuntimeError(f"Timestamp collision after {max_retries} retries (1s)")


def publish(workflow_dir: Path, name: str, ts: str, publisher: str) -> None:
    """Copy draft to canonical workflow file atomically.
    
    Appends a line to PUBLISHED.log with format:
    YYYY-MM-DDTHH:MM:SSZ  {publisher}  published {ts}
    
    Args:
        workflow_dir: Base directory containing workflows
        name: Workflow name
        ts: Draft timestamp to publish
        publisher: Publisher identifier (e.g., "dashboard-ui  alice@host")
        
    Raises:
        FileNotFoundError: If the draft does not exist
    """
    # Read draft content
    draft_file = _draft_path(workflow_dir, name, ts)
    content = draft_file.read_text()
    
    # Atomic write to canonical location
    canonical_file = _canonical_path(workflow_dir, name)
    temp_file = canonical_file.with_suffix('.yaml.tmp')
    temp_file.write_text(content)
    os.chmod(temp_file, FILE_MODE)
    temp_file.replace(canonical_file)
    
    # Append to PUBLISHED.log
    log_file = _published_log_path(workflow_dir, name)
    log_timestamp = datetime.now(timezone.utc).strftime(LOG_TIMESTAMP_FORMAT)
    log_line = f"{log_timestamp}  {publisher}  published {ts}\n"
    
    with open(log_file, 'a') as f:
        f.write(log_line)
    
    # Ensure log has correct permissions
    os.chmod(log_file, FILE_MODE)


def delete_draft(workflow_dir: Path, name: str, ts: str) -> None:
    """Delete a single draft.
    
    Idempotent: does not raise error if draft doesn't exist.
    
    Args:
        workflow_dir: Base directory containing workflows
        name: Workflow name
        ts: Timestamp of draft to delete
    """
    draft_file = _draft_path(workflow_dir, name, ts)
    draft_file.unlink(missing_ok=True)


def prune(workflow_dir: Path, name: str, keep: int = KEEP_DEFAULT) -> List[str]:
    """Delete oldest drafts to retain only the most recent `keep` drafts.
    
    Args:
        workflow_dir: Base directory containing workflows
        name: Workflow name
        keep: Number of most recent drafts to retain (default: 50)
        
    Returns:
        List of deleted timestamp strings
    """
    drafts = list_drafts(workflow_dir, name)
    
    if len(drafts) <= keep:
        return []
    
    # Delete oldest (first in sorted list)
    to_delete = drafts[:-keep] if keep > 0 else drafts
    
    for ts in to_delete:
        delete_draft(workflow_dir, name, ts)
    
    return to_delete

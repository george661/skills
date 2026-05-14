"""Workspace diff/apply substrate for orchestrator edit boundary.

Phase 2 of GW-5928 (orchestrator edit boundary). Pure-Python diff/apply
library used by Phase 3 (CLI) and Phase 5 (dashboard UI).
"""
from __future__ import annotations

import difflib
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Optional

logger = logging.getLogger(__name__)

ManifestKind = Literal["workflow_yaml", "prompt_file", "bash_script"]
ChangeKind = Literal["modified", "new"]


@dataclass(frozen=True)
class Change:
    """A detected change in a workspace."""
    workspace_path: str  # relative to workspace root
    source_path: Optional[Path]  # absolute source path; None for kind="new"
    kind: ChangeKind
    diff: str  # unified diff text
    manifest_kind: Optional[ManifestKind]  # None for new files


@dataclass(frozen=True)
class ApplyResult:
    """Result of applying a change."""
    applied: bool
    source_path: Path  # where the file landed
    commit_sha: Optional[str] = None  # set when commit=True succeeded
    error: Optional[str] = None  # set on commit failure or other errors


def iter_changes(workspace: Path) -> Iterable[Change]:
    """Yield Change objects for modified seeded files and new files under .workflow/.
    
    Reads <workspace>/.workflow/.manifest.json. Returns empty iterator if missing
    (programmatic workflows have no source — nothing to diff).
    
    For each manifest entry: compares workspace file content vs. source file content.
    Only emits when content differs. Source-missing is logged and skipped (not raised).
    
    For files under .workflow/ that have no manifest entry: yields kind="new".
    
    Skips: anything outside .workflow/ and outside src/ (scratch artifacts).
    Note: src/ is git-managed; surfacing src/ diffs is Phase 4 of the design,
    not Phase 2 — out of scope for this ticket.
    """
    manifest_path = workspace / ".workflow" / ".manifest.json"
    
    if not manifest_path.exists():
        return
    
    try:
        manifest = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read manifest at %s: %s", manifest_path, e)
        return
    
    # Track which workspace files are in the manifest
    manifest_workspace_paths = set()
    
    # Check manifest entries for modifications
    for entry in manifest:
        workspace_rel_path = entry["workspace_path"]
        source_path_str = entry["source_path"]
        manifest_kind = entry["kind"]
        
        manifest_workspace_paths.add(workspace_rel_path)
        
        source_path = Path(source_path_str)
        workspace_file = workspace / workspace_rel_path
        
        # Check if source exists
        if not source_path.exists():
            logger.warning(
                "Source file %s does not exist (manifest entry %s), skipping",
                source_path,
                workspace_rel_path,
            )
            continue
        
        # Check if workspace file exists
        if not workspace_file.exists():
            continue
        
        # Compare content
        try:
            source_content = source_path.read_text()
            workspace_content = workspace_file.read_text()
        except OSError as e:
            logger.warning("Failed to read files for %s: %s", workspace_rel_path, e)
            continue
        
        if source_content == workspace_content:
            continue
        
        # Generate diff
        # unified_diff lines are already newline-terminated, so use "".join() not "\n".join()
        diff = "".join(
            difflib.unified_diff(
                source_content.splitlines(keepends=True),
                workspace_content.splitlines(keepends=True),
                fromfile=str(source_path),
                tofile=str(workspace_file),
            )
        )
        
        yield Change(
            workspace_path=workspace_rel_path,
            source_path=source_path,
            kind="modified",
            diff=diff,
            manifest_kind=manifest_kind,
        )
    
    # Check for new files under .workflow/
    workflow_dir = workspace / ".workflow"
    if not workflow_dir.exists():
        return
    
    for root, _dirs, files in os.walk(workflow_dir):
        root_path = Path(root)
        for filename in files:
            file_path = root_path / filename
            
            # Skip .manifest.json itself
            if file_path == manifest_path:
                continue
            
            # Get relative path from workspace
            try:
                rel_path = file_path.relative_to(workspace)
            except ValueError:
                continue
            
            rel_path_str = str(rel_path)
            
            # Skip if in manifest
            if rel_path_str in manifest_workspace_paths:
                continue
            
            # This is a new file
            try:
                content = file_path.read_text()
            except OSError as e:
                logger.warning("Failed to read new file %s: %s", file_path, e)
                continue
            
            yield Change(
                workspace_path=rel_path_str,
                source_path=None,
                kind="new",
                diff="",  # No diff for new files
                manifest_kind=None,
            )


def apply_change(
    change: Change,
    workspace: Path,
    target_path: Optional[Path] = None,
    *,
    commit: bool = False,
) -> ApplyResult:
    """Write a Change back to the source tree.

    Args:
        change: The Change to apply
        workspace: Workspace root (needed to locate the workspace file)
        target_path: For kind="new" files, where to write the file
        commit: If True, attempt git commit after copying

    For kind="modified": copies workspace file -> change.source_path.
      target_path is ignored (manifest already has the source path).

    For kind="new": requires target_path; raises ValueError if missing.
      Suggested target generation lives in suggest_target(change) (helper).

    With commit=True: best-effort git add <path> && git commit -m <msg> in
      the source repo, auto-detected by running git -C <source_dir> rev-parse
      --is-inside-work-tree. If source isn't a git working tree:
      ApplyResult.applied=True, error="<reason>", commit_sha=None.
      The file IS still copied — commit failure is non-fatal.
    """
    if change.kind == "new":
        if target_path is None:
            raise ValueError("target_path is required for new files (kind='new')")
        dest = target_path
    else:
        if change.source_path is None:
            raise ValueError("source_path must be set for modified files")
        dest = change.source_path

    # Read workspace file content
    workspace_file = workspace / change.workspace_path
    try:
        content = workspace_file.read_text()
    except OSError as e:
        return ApplyResult(
            applied=False,
            source_path=dest,
            error=f"Failed to read workspace file: {e}",
        )

    # Write to destination
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
    except OSError as e:
        return ApplyResult(
            applied=False,
            source_path=dest,
            error=f"Failed to write destination file: {e}",
        )

    # If commit requested, attempt git operations
    commit_sha = None
    error = None

    if commit:
        # Check if dest is in a git working tree
        try:
            result = subprocess.run(
                ["git", "-C", str(dest.parent), "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                timeout=5,
                text=True,
            )
            if result.returncode != 0:
                error = "Not a git working tree"
            else:
                # Try to commit
                try:
                    # Add file
                    subprocess.run(
                        ["git", "-C", str(dest.parent), "add", dest.name],
                        capture_output=True,
                        timeout=5,
                        check=True,
                    )
                    # Commit
                    commit_msg = f"Apply workspace change: {change.workspace_path}"
                    result = subprocess.run(
                        ["git", "-C", str(dest.parent), "commit", "-m", commit_msg],
                        capture_output=True,
                        timeout=5,
                        text=True,
                    )
                    if result.returncode == 0:
                        # Get commit SHA
                        sha_result = subprocess.run(
                            ["git", "-C", str(dest.parent), "rev-parse", "HEAD"],
                            capture_output=True,
                            timeout=5,
                            text=True,
                            check=True,
                        )
                        commit_sha = sha_result.stdout.strip()
                    else:
                        # Git commit failed - capture both stdout and stderr
                        error = f"Git commit failed: {result.stdout or result.stderr}"
                except (subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
                    error = f"Git commit failed: {e}"
        except (subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
            error = f"Not a git working tree: {e}"

    return ApplyResult(
        applied=True,
        source_path=dest,
        commit_sha=commit_sha,
        error=error,
    )


def suggest_target(
    change: Change,
    workflows_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Suggest a target path for a new file (kind="new" with no manifest entry).
    
    .workflow/prompts/foo.md -> <workflows_dir>/prompts/foo.md
    .workflow/scripts/foo.sh -> <workflows_dir>/scripts/foo.sh
    Returns None when the workspace_path is unmappable or workflows_dir is None.
    """
    if workflows_dir is None:
        return None
    
    workspace_path = change.workspace_path
    
    # Check for .workflow/prompts/ pattern
    if workspace_path.startswith(".workflow/prompts/"):
        rel = workspace_path[len(".workflow/"):]
        return workflows_dir / rel
    
    # Check for .workflow/scripts/ pattern
    if workspace_path.startswith(".workflow/scripts/"):
        rel = workspace_path[len(".workflow/"):]
        return workflows_dir / rel
    
    return None

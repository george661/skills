"""Helper module for workspace pending changes resolution and operations."""
from pathlib import Path
from typing import List, Optional

from dag_executor import workspaces_diff

from .models import PendingChange


def get_pending_changes(
    workspace_path: Path,
    workflows_dir: Optional[Path] = None
) -> List[PendingChange]:
    """Get list of pending changes for a workspace.

    Args:
        workspace_path: Absolute path to workspace directory
        workflows_dir: Optional workflows directory for suggest_target
    
    Returns:
        List of PendingChange objects
    """
    changes = []

    for change in workspaces_diff.iter_changes(workspace_path):
        # Compute suggested_target_path for new files only
        suggested_target_str: Optional[str] = None
        if change.kind == "new":
            suggested_target_path = workspaces_diff.suggest_target(change, workflows_dir=workflows_dir)
            if suggested_target_path:
                suggested_target_str = str(suggested_target_path)

        # Extract kind value (handle both enum and string)
        kind_value = getattr(change.kind, 'value', None)
        kind_str = kind_value if kind_value is not None else str(change.kind)

        # Extract manifest_kind value (handle both enum and string)
        manifest_kind_str: Optional[str] = None
        if change.manifest_kind:
            manifest_kind_value = getattr(change.manifest_kind, 'value', None)
            manifest_kind_str = manifest_kind_value if manifest_kind_value is not None else str(change.manifest_kind)

        changes.append(PendingChange(
            workspace_path=change.workspace_path,
            source_path=str(change.source_path) if change.source_path else None,
            kind=kind_str,
            diff=change.diff,
            manifest_kind=manifest_kind_str,
            suggested_target_path=suggested_target_str
        ))

    return changes

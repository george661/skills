"""Path resolution logic for workflow-relative references."""
import os
from pathlib import Path
from typing import List, Optional


def _resolve_workflow_relative(
    reference: str,
    parent_source: Optional[Path],
    suffixes: Optional[List[str]] = None
) -> Optional[Path]:
    """Resolve a workflow-relative reference to a concrete file path.

    A reference can be:
      - an absolute or relative filesystem path (with or without extension)
      - a bare name (e.g. "validate-epic-audit-children") expected to
        live alongside the parent workflow or in a known install location

    Search order:
      1. The literal string as a path (covers both ".yaml-ful" and absolute refs)
      2. `<parent-dir>/<name>` with each suffix — the common co-located case
      3. Each entry in `DAG_DASHBOARD_WORKFLOWS_DIR` (colon-separated)
      4. Repo root directories (commands/, workflows/)
      5. `~/.claude/workflows/<name>`

    Args:
        reference: The reference string from the workflow (e.g., "../../commands/foo.md")
        parent_source: Path to the parent workflow YAML file (optional)
        suffixes: List of suffixes to try (e.g., [".yaml", ".yml"]). If None, no suffixes.

    Returns:
        The first existing file path, or None if nothing matched.
    """
    # 1. Literal path (handles e.g. "foo/bar.yaml" or "/abs/path.yaml").
    # Require a regular file — a matching directory name at CWD (e.g. a
    # stale `.dag-checkpoints/` leak) should not pre-empt the search.
    # Return resolved path for consistency.
    direct = Path(reference)
    if direct.is_file():
        return direct.resolve()

    # Build candidate names with suffixes
    candidate_names: List[str] = [reference]
    if suffixes:
        # Only add suffixes if reference doesn't already have one
        has_suffix = any(reference.endswith(ext) for ext in suffixes)
        if not has_suffix:
            candidate_names.extend([reference + ext for ext in suffixes])

    search_dirs: List[Path] = []
    
    # 2. Parent workflow's directory
    if parent_source is not None:
        search_dirs.append(parent_source.parent)
    
    # 3. DAG_DASHBOARD_WORKFLOWS_DIR (colon-separated list)
    env_dirs = os.environ.get("DAG_DASHBOARD_WORKFLOWS_DIR", "")
    if env_dirs:
        search_dirs.extend(Path(d) for d in env_dirs.split(os.pathsep) if d)
    
    # 4. Repo root directories (for commands/, workflows/)
    # Try to find repo root by walking up from parent_source or CWD
    repo_root = _find_repo_root(parent_source)
    if repo_root:
        search_dirs.append(repo_root / "commands")
        search_dirs.append(repo_root / "workflows")
    
    # 5. ~/.claude/workflows
    search_dirs.append(Path.home() / ".claude" / "workflows")

    for base in search_dirs:
        for name in candidate_names:
            candidate = base / name
            if candidate.is_file():
                return candidate

    return None


def _find_repo_root(start_path: Optional[Path]) -> Optional[Path]:
    """Find the repository root by looking for .git directory.
    
    Args:
        start_path: Starting path (usually workflow file path). If None, uses CWD.
        
    Returns:
        Path to repo root, or None if not found.
    """
    current = start_path.parent if start_path and start_path.is_file() else (start_path or Path.cwd())
    
    # Walk up to find .git
    for _ in range(10):  # Reasonable depth limit
        if (current / ".git").exists():
            return current
        if current.parent == current:  # Reached root
            break
        current = current.parent
    
    return None


# Maximum recursion depth for sub-workflow execution and seeding
MAX_RECURSION_DEPTH = 5


def _resolve_sub_workflow(reference: str, parent_source: Optional[Path]) -> Optional[Path]:
    """Resolve a `command:` field to a concrete YAML path.

    Delegates to _resolve_workflow_relative with .yaml/.yml suffixes.

    Args:
        reference: Command reference string (workflow name or path)
        parent_source: Path to parent workflow file

    Returns:
        Path to workflow file, or None if not found
    """
    return _resolve_workflow_relative(reference, parent_source, suffixes=[".yaml", ".yml"])

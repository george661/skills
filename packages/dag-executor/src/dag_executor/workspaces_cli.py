"""CLI commands for managing workflow workspaces."""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional, Tuple

from . import workspaces_diff


def _resolve_workspace_root() -> Path:
    """Resolve workspace root directory using same logic as executor."""
    env_root = os.environ.get("DAG_WORKSPACE_ROOT")
    if env_root:
        return Path(env_root).expanduser()
    return Path.home() / ".dag-dashboard" / "workspaces"


def _get_workspace_info(workspace_path: Path) -> Tuple[str, float, float]:
    """Get workspace metadata: run_id, age in days, size in MB."""
    run_id = workspace_path.name
    
    # Age from directory creation time
    try:
        ctime = workspace_path.stat().st_ctime
        age_days = (datetime.now().timestamp() - ctime) / 86400
    except OSError:
        age_days = 0
    
    # Size calculation (recursive)
    total_size = 0
    try:
        for item in workspace_path.rglob("*"):
            if item.is_file():
                total_size += item.stat().st_size
    except OSError:
        pass
    
    size_mb = total_size / (1024 * 1024)
    
    return run_id, age_days, size_mb


def cmd_list(args: argparse.Namespace) -> int:
    """List all workspaces."""
    workspace_root = _resolve_workspace_root()
    
    if not workspace_root.exists():
        print(f"No workspaces found (expected root: {workspace_root})")
        return 0
    
    workspaces = sorted(workspace_root.iterdir(), key=lambda p: p.stat().st_ctime, reverse=True)
    
    if not workspaces:
        print(f"No workspaces found in {workspace_root}")
        return 0
    
    print(f"Workspaces in {workspace_root}:\n")
    print(f"{'RUN_ID':<40} {'AGE (days)':<12} {'SIZE (MB)':<12}")
    print("-" * 70)
    
    for workspace in workspaces:
        if not workspace.is_dir():
            continue
        
        run_id, age_days, size_mb = _get_workspace_info(workspace)
        print(f"{run_id:<40} {age_days:<12.1f} {size_mb:<12.1f}")
    
    print(f"\nTotal: {len(workspaces)} workspace(s)")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    """Show details for a specific workspace."""
    workspace_root = _resolve_workspace_root()
    workspace_path = workspace_root / args.run_id
    
    if not workspace_path.exists():
        print(f"Workspace not found: {workspace_path}", file=sys.stderr)
        return 1
    
    run_id, age_days, size_mb = _get_workspace_info(workspace_path)
    
    print(f"Workspace: {run_id}")
    print(f"Path: {workspace_path}")
    print(f"Age: {age_days:.1f} days")
    print(f"Size: {size_mb:.1f} MB")
    
    # Check for git repo
    src_path = workspace_path / "src"
    if src_path.exists() and (src_path / ".git").exists():
        print("\nGit repository:")
        try:
            # Get current commit
            result = subprocess.run(
                ["git", "-C", str(src_path), "log", "-1", "--oneline"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                print(f"  {result.stdout.strip()}")
            
            # Get remote URL
            result = subprocess.run(
                ["git", "-C", str(src_path), "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                print(f"  Remote: {result.stdout.strip()}")
        except subprocess.TimeoutExpired:
            print("  (git command timed out)")
        except Exception as e:
            print(f"  (error reading git info: {e})")
    
    # List contents
    print("\nContents:")
    try:
        for item in sorted(workspace_path.iterdir()):
            if item.is_dir():
                print(f"  {item.name}/")
            else:
                size = item.stat().st_size / 1024
                print(f"  {item.name} ({size:.1f} KB)")
    except OSError as e:
        print(f"  (error listing contents: {e})")
    
    return 0


def _resolve_workflows_dir() -> Optional[Path]:
    """Resolve workflows directory from environment variable."""
    env_dirs = os.environ.get("DAG_DASHBOARD_WORKFLOWS_DIR", "")
    if not env_dirs:
        return None

    # Split by os.pathsep (: on POSIX, ; on Windows)
    dirs = env_dirs.split(os.pathsep)
    if not dirs:
        return None

    # Return first entry
    first_dir = Path(dirs[0]).expanduser()
    return first_dir if first_dir.exists() else None


def cmd_diff(args: argparse.Namespace) -> int:
    """Print diff for workspace changes."""
    workspace_root = _resolve_workspace_root()
    workspace_path = workspace_root / args.run_id

    if not workspace_path.exists():
        print(f"Workspace not found: {workspace_path}", file=sys.stderr)
        return 1

    changes = list(workspaces_diff.iter_changes(workspace_path))

    if not changes:
        print("No changes")
        return 0

    for change in changes:
        if change.kind == "new":
            print(f"--- /dev/null")
            print(f"+++ {change.workspace_path}")
            print(f"(new file)")
            # Show first 40 lines of content
            workspace_file = workspace_path / change.workspace_path
            content = workspace_file.read_text()
            lines = content.split("\n")[:40]
            for line in lines:
                print(f"+{line}")
            if len(content.split("\n")) > 40:
                print("...")
        else:
            print(f"--- a/{change.workspace_path}")
            print(f"+++ b/{change.workspace_path}")
            print(change.diff)

    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    """Apply workspace changes back to source."""
    # Validate flags
    if not args.all and not args.file:
        print("Error: Either --all or --file is required", file=sys.stderr)
        print("Usage: dag-exec workspaces promote <run_id> --all [--commit]", file=sys.stderr)
        print("   or: dag-exec workspaces promote <run_id> --file <path> [--commit] [--target <path>]", file=sys.stderr)
        return 1

    workspace_root = _resolve_workspace_root()
    workspace_path = workspace_root / args.run_id

    if not workspace_path.exists():
        print(f"Workspace not found: {workspace_path}", file=sys.stderr)
        return 1

    changes = list(workspaces_diff.iter_changes(workspace_path))

    if not changes:
        print("No changes to promote")
        return 0

    # Filter to selected changes
    if args.file:
        changes = [c for c in changes if c.workspace_path == args.file]
        if not changes:
            print(f"No changes found for file: {args.file}", file=sys.stderr)
            return 1

    # Check for new files requiring --target
    for change in changes:
        if change.kind == "new" and not args.target:
            # Try to suggest target
            workflows_dir = _resolve_workflows_dir()
            suggested = workspaces_diff.suggest_target(change, workflows_dir=workflows_dir)

            if suggested:
                print(f"Error: New file '{change.workspace_path}' requires --target", file=sys.stderr)
                print(f"Suggested target: {suggested}", file=sys.stderr)
            else:
                print(f"Error: New file '{change.workspace_path}' requires --target", file=sys.stderr)
                print(f"Workspace path: {workspace_path / change.workspace_path}", file=sys.stderr)

            return 1

    # Apply changes
    any_failed = False
    for change in changes:
        target_path = Path(args.target) if args.target else None
        result = workspaces_diff.apply_change(
            change,
            workspace_path,
            target_path=target_path,
            commit=args.commit
        )

        if not result.applied:
            print(f"Failed: {change.workspace_path} ({result.error})", file=sys.stderr)
            any_failed = True
        elif result.error:
            # Applied but commit failed
            print(f"Applied: {result.source_path}; commit failed: {result.error}")
        else:
            print(f"Applied: {result.source_path}")

    return 1 if any_failed else 0


def cmd_discard(args: argparse.Namespace) -> int:
    """Discard workspace changes (restore from source or delete new files)."""
    # Validate flags
    if not args.all and not args.file:
        print("Error: Either --all or --file is required", file=sys.stderr)
        print("Usage: dag-exec workspaces discard <run_id> --all", file=sys.stderr)
        print("   or: dag-exec workspaces discard <run_id> --file <path>", file=sys.stderr)
        return 1

    workspace_root = _resolve_workspace_root()
    workspace_path = workspace_root / args.run_id

    if not workspace_path.exists():
        print(f"Workspace not found: {workspace_path}", file=sys.stderr)
        return 1

    changes = list(workspaces_diff.iter_changes(workspace_path))

    if not changes:
        print("No changes to discard")
        return 0

    # Filter to selected changes
    if args.file:
        changes = [c for c in changes if c.workspace_path == args.file]
        if not changes:
            print(f"No changes found for file: {args.file}", file=sys.stderr)
            return 1

    # Discard changes
    for change in changes:
        workspace_file = workspace_path / change.workspace_path

        if change.kind == "new":
            # Delete new file
            workspace_file.unlink()
            print(f"Discarded: {change.workspace_path} (deleted)")
        else:
            # Restore from source
            if change.source_path and change.source_path.exists():
                workspace_file.write_text(change.source_path.read_text())
                print(f"Discarded: {change.workspace_path} (restored from source)")
            else:
                print(f"Warning: Cannot restore {change.workspace_path} - source not found", file=sys.stderr)

    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    """Delete old workspaces."""
    if not args.older_than:
        print("Error: --older-than is required for safety", file=sys.stderr)
        print("Example: dag-exec workspaces prune --older-than 7d")
        return 1
    
    # Parse duration
    duration_str = args.older_than
    if duration_str.endswith("d"):
        days = float(duration_str[:-1])
    elif duration_str.endswith("h"):
        days = float(duration_str[:-1]) / 24
    else:
        print(f"Error: Invalid duration format '{duration_str}' (use 7d or 24h)", file=sys.stderr)
        return 1
    
    cutoff = datetime.now() - timedelta(days=days)
    
    workspace_root = _resolve_workspace_root()
    if not workspace_root.exists():
        print(f"No workspaces found (expected root: {workspace_root})")
        return 0
    
    deleted = []
    errors = []
    
    for workspace in workspace_root.iterdir():
        if not workspace.is_dir():
            continue
        
        try:
            ctime = workspace.stat().st_ctime
            created = datetime.fromtimestamp(ctime)
            
            if created < cutoff:
                if args.dry_run:
                    print(f"Would delete: {workspace.name} (age: {(datetime.now() - created).days} days)")
                else:
                    import shutil
                    shutil.rmtree(workspace)
                    deleted.append(workspace.name)
                    print(f"Deleted: {workspace.name}")
        except Exception as e:
            errors.append((workspace.name, str(e)))
    
    if args.dry_run:
        print(f"\nDry run complete. Would delete {len(deleted)} workspace(s).")
        print("Run without --dry-run to actually delete.")
    else:
        print(f"\nDeleted {len(deleted)} workspace(s).")
    
    if errors:
        print(f"\nErrors ({len(errors)}):", file=sys.stderr)
        for name, error in errors:
            print(f"  {name}: {error}", file=sys.stderr)
        return 1
    
    return 0


def run_workspaces(args: argparse.Namespace) -> int:
    """Main entry point for workspaces subcommand."""
    if not hasattr(args, "workspaces_cmd") or not args.workspaces_cmd:
        print("Error: missing subcommand (list, show, prune, diff, promote, discard)", file=sys.stderr)
        return 1

    if args.workspaces_cmd == "list":
        return cmd_list(args)
    elif args.workspaces_cmd == "show":
        if not hasattr(args, "run_id"):
            print("Error: run_id is required", file=sys.stderr)
            return 1
        return cmd_show(args)
    elif args.workspaces_cmd == "prune":
        return cmd_prune(args)
    elif args.workspaces_cmd == "diff":
        if not hasattr(args, "run_id"):
            print("Error: run_id is required", file=sys.stderr)
            return 1
        return cmd_diff(args)
    elif args.workspaces_cmd == "promote":
        if not hasattr(args, "run_id"):
            print("Error: run_id is required", file=sys.stderr)
            return 1
        return cmd_promote(args)
    elif args.workspaces_cmd == "discard":
        if not hasattr(args, "run_id"):
            print("Error: run_id is required", file=sys.stderr)
            return 1
        return cmd_discard(args)
    else:
        print(f"Error: unknown subcommand '{args.workspaces_cmd}'", file=sys.stderr)
        return 1


def add_workspaces_parser(subparsers: Any) -> None:
    """Add workspaces subcommand parser.

    Args:
        subparsers: Either a _SubParsersAction from add_subparsers() or
                    an internal _SubParsersAction._group_actions[0] for CLI compatibility.
    """
    # Handle both cases: subparsers could be the result of add_subparsers()
    # or it could be parser._subparsers (internal structure)
    if hasattr(subparsers, 'add_parser'):
        # This is a proper SubParsersAction
        workspaces_subs = subparsers
    elif hasattr(subparsers, '_group_actions'):
        # This is parser._subparsers from cli.py
        workspaces_subs = subparsers._group_actions[0]
    else:
        raise TypeError(f"Unexpected subparsers type: {type(subparsers)}")

    # list
    workspaces_subs.add_parser("list", help="List all workspaces")

    # show
    show = workspaces_subs.add_parser("show", help="Show workspace details")
    show.add_argument("run_id", help="Run ID of workspace to show")

    # prune
    prune = workspaces_subs.add_parser("prune", help="Delete old workspaces")
    prune.add_argument("--older-than", help="Delete workspaces older than duration (e.g., 7d, 24h)")
    prune.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")

    # diff
    diff = workspaces_subs.add_parser("diff", help="Show diff of workspace changes")
    diff.add_argument("run_id", help="Run ID of workspace to diff")

    # promote
    promote = workspaces_subs.add_parser("promote", help="Apply workspace changes back to source")
    promote.add_argument("run_id", help="Run ID of workspace to promote")
    promote_group = promote.add_mutually_exclusive_group(required=True)
    promote_group.add_argument("--all", action="store_true", help="Promote all changes")
    promote_group.add_argument("--file", help="Promote specific file (workspace-relative path)")
    promote.add_argument("--commit", action="store_true", help="Also git commit the changes")
    promote.add_argument("--target", help="Target path for new files (required for new files)")

    # discard
    discard = workspaces_subs.add_parser("discard", help="Discard workspace changes")
    discard.add_argument("run_id", help="Run ID of workspace to discard")
    discard_group = discard.add_mutually_exclusive_group(required=True)
    discard_group.add_argument("--all", action="store_true", help="Discard all changes")
    discard_group.add_argument("--file", help="Discard specific file (workspace-relative path)")

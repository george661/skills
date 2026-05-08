"""CLI commands for managing workflow workspaces."""
import argparse
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple


def _resolve_workspace_root() -> Path:
    """Resolve workspace root directory using same logic as executor."""
    env_root = os.environ.get("DAG_WORKSPACE_ROOT")
    if env_root:
        return Path(env_root).expanduser()
    return Path.home() / ".dag-dashboard" / "workspaces"


def _get_workspace_info(workspace_path: Path) -> Tuple[str, float, int]:
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
        print("Error: missing subcommand (list, show, prune)", file=sys.stderr)
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
    else:
        print(f"Error: unknown subcommand '{args.workspaces_cmd}'", file=sys.stderr)
        return 1


def add_workspaces_parser(subparsers) -> None:
    """Add workspaces subcommand parser."""
    workspaces = subparsers.add_parser(
        "workspaces",
        help="Manage workflow workspaces"
    )
    
    workspaces_subs = workspaces.add_subparsers(dest="workspaces_cmd")
    
    # list
    workspaces_subs.add_parser("list", help="List all workspaces")
    
    # show
    show = workspaces_subs.add_parser("show", help="Show workspace details")
    show.add_argument("run_id", help="Run ID of workspace to show")
    
    # prune
    prune = workspaces_subs.add_parser("prune", help="Delete old workspaces")
    prune.add_argument("--older-than", help="Delete workspaces older than duration (e.g., 7d, 24h)")
    prune.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")

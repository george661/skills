"""
CLI subcommands for workflow drafts management.

Supports both local mode (filesystem via drafts_fs) and remote mode (HTTP API).
"""

import argparse
import difflib
import os
import socket
import sys
from pathlib import Path
from typing import Any

import httpx


def _resolve_workflow_dir(args: Any) -> Path:
    """Resolve workflow directory from --workflows-dir, env var, or default."""
    if hasattr(args, 'workflows_dir') and args.workflows_dir:
        return Path(args.workflows_dir)

    # Fall back to first entry in DAG_DASHBOARD_WORKFLOWS_DIR
    env_dirs = os.environ.get('DAG_DASHBOARD_WORKFLOWS_DIR', '')
    if env_dirs:
        return Path(env_dirs.split(':')[0])

    return Path('.')


def _get_remote_token(args: Any) -> str:
    """Get remote token from --token or env var. Exit 2 if missing."""
    if hasattr(args, 'token') and args.token:
        return str(args.token)
    
    token = os.environ.get('DAG_EXEC_DRAFTS_TOKEN')
    if not token:
        print("Error: --remote requires --token or DAG_EXEC_DRAFTS_TOKEN env var", file=sys.stderr)
        sys.exit(2)
    
    return token


def _confirm(prompt: str) -> bool:
    """Read confirmation from stdin. Accept y/Y/yes."""
    # Allow stdin to be mocked (e.g., StringIO in tests)
    try:
        response = input(prompt).strip().lower()
        return response in ('y', 'yes')
    except (EOFError, KeyboardInterrupt):
        return False


def run_drafts_list(args: Any) -> None:
    """List all drafts for a workflow."""
    if args.remote:
        token = _get_remote_token(args)
        url = f"{args.remote.rstrip('/')}/api/workflows/{args.workflow}/drafts"
        
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()
            data = response.json()
            drafts = data.get('drafts', [])
    else:
        # Local mode - import late to avoid module dependency
        from dag_executor.drafts_fs import list_drafts
        
        wf_dir = _resolve_workflow_dir(args)
        drafts = list_drafts(wf_dir, args.workflow)
    
    if args.json:
        import json
        print(json.dumps(drafts))
    else:
        for ts in drafts:
            print(ts)


def run_drafts_diff(args: Any) -> None:
    """Show diff between drafts or draft vs canonical."""
    if args.remote:
        token = _get_remote_token(args)
        base_url = args.remote.rstrip('/')
        
        with httpx.Client(timeout=30.0) as client:
            # Fetch first draft/file
            url_a = f"{base_url}/api/workflows/{args.workflow}/drafts/{args.ts_a}"
            response_a = client.get(url_a, headers={"Authorization": f"Bearer {token}"})
            response_a.raise_for_status()
            content_a = response_a.text
            
            # Fetch second draft or canonical
            if args.ts_b:
                url_b = f"{base_url}/api/workflows/{args.workflow}/drafts/{args.ts_b}"
            else:
                url_b = f"{base_url}/api/workflows/{args.workflow}"
            
            response_b = client.get(url_b, headers={"Authorization": f"Bearer {token}"})
            response_b.raise_for_status()
            content_b = response_b.text
    else:
        # Local mode
        from dag_executor.drafts_fs import read_draft
        
        wf_dir = _resolve_workflow_dir(args)
        
        try:
            content_a = read_draft(wf_dir, args.workflow, args.ts_a)
            
            if args.ts_b:
                content_b = read_draft(wf_dir, args.workflow, args.ts_b)
            else:
                # Read canonical
                canonical_path = Path(wf_dir) / f"{args.workflow}.yaml"
                with open(canonical_path, 'r') as f:
                    content_b = f.read()
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    
    # Generate unified diff
    fromfile = f"drafts/{args.workflow}/{args.ts_a}.yaml"
    if args.ts_b:
        tofile = f"drafts/{args.workflow}/{args.ts_b}.yaml"
    else:
        tofile = f"{args.workflow}.yaml"
    
    diff = difflib.unified_diff(
        content_a.splitlines(keepends=True),
        content_b.splitlines(keepends=True),
        fromfile=fromfile,
        tofile=tofile
    )
    
    for line in diff:
        print(line, end='')


def run_drafts_restore(args: Any) -> None:
    """Restore a draft as the canonical workflow."""
    if not args.yes and not _confirm(f"Overwrite {args.workflow}.yaml with draft {args.timestamp}? [y/N] "):
        print("Aborted.", file=sys.stderr)
        sys.exit(1)
    
    if args.remote:
        token = _get_remote_token(args)
        base_url = args.remote.rstrip('/')

        with httpx.Client(timeout=30.0) as client:
            # Use publish endpoint to restore (publish IS the restore mechanism)
            url = f"{base_url}/api/workflows/{args.workflow}/drafts/{args.timestamp}/publish"
            response = client.post(url, headers={"Authorization": f"Bearer {token}"})

            if response.status_code != 200 and response.status_code != 201:
                print(f"Error {response.status_code}: {response.text}", file=sys.stderr)
                sys.exit(1)
    else:
        # Local mode
        from dag_executor.drafts_fs import read_draft
        
        wf_dir = _resolve_workflow_dir(args)
        draft_content = read_draft(wf_dir, args.workflow, args.timestamp)
        
        # Atomic write: write to temp file then rename
        canonical_path = Path(wf_dir) / f"{args.workflow}.yaml"
        temp_path = Path(wf_dir) / f"{args.workflow}.yaml.tmp"
        
        temp_path.write_text(draft_content)
        temp_path.replace(canonical_path)  # Atomic on all platforms
    
    print(f"Restored {args.workflow}.yaml from draft {args.timestamp}")


def run_drafts_publish(args: Any) -> None:
    """Publish a draft as the canonical workflow (with validation)."""
    if args.remote:
        token = _get_remote_token(args)
        url = f"{args.remote.rstrip('/')}/api/workflows/{args.workflow}/drafts/{args.timestamp}/publish"
        
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, headers={"Authorization": f"Bearer {token}"})
            
            if response.status_code != 200 and response.status_code != 201:
                print(f"Error {response.status_code}: {response.text}", file=sys.stderr)
                sys.exit(1)
    else:
        # Local mode - validate then publish
        from dag_executor.drafts_fs import read_draft, publish
        from dag_executor.parser import load_workflow
        
        wf_dir = _resolve_workflow_dir(args)
        draft_content = read_draft(wf_dir, args.workflow, args.timestamp)
        
        # Validate schema
        try:
            # Write to temp file for validation
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
                tmp.write(draft_content)
                tmp_path = tmp.name
            
            try:
                load_workflow(tmp_path)
            finally:
                os.unlink(tmp_path)
        except Exception as e:
            print(f"Validation error: {e}", file=sys.stderr)
            sys.exit(1)
        
        # Get publisher string
        user = os.environ.get('USER', 'unknown')
        host = socket.gethostname()
        publisher = f"cli  {user}@{host}"
        
        # Publish
        publish(wf_dir, args.workflow, args.timestamp, publisher)
    
    print(f"Published draft {args.timestamp} -> {args.workflow}.yaml")


def run_drafts_delete(args: Any) -> None:
    """Delete a draft."""
    if not args.yes and not _confirm(f"Delete draft {args.timestamp} of {args.workflow}? [y/N] "):
        print("Aborted.", file=sys.stderr)
        sys.exit(1)
    
    if args.remote:
        token = _get_remote_token(args)
        url = f"{args.remote.rstrip('/')}/api/workflows/{args.workflow}/drafts/{args.timestamp}"
        
        with httpx.Client(timeout=30.0) as client:
            response = client.delete(url, headers={"Authorization": f"Bearer {token}"})
            
            # 404 is treated as success (idempotent)
            if response.status_code not in (200, 201, 204, 404):
                print(f"Error {response.status_code}: {response.text}", file=sys.stderr)
                sys.exit(1)
    else:
        # Local mode
        from dag_executor.drafts_fs import delete_draft
        
        wf_dir = _resolve_workflow_dir(args)
        delete_draft(wf_dir, args.workflow, args.timestamp)
    
    print(f"Deleted draft {args.timestamp}")


def run_drafts(argv: list[str]) -> None:
    """Main entry point for drafts subcommand."""
    parser = argparse.ArgumentParser(
        prog='dag-exec drafts',
        description='Manage workflow drafts'
    )
    
    subparsers = parser.add_subparsers(dest='subcommand', help='Subcommand')
    
    # List
    list_parser = subparsers.add_parser('list', help='List all drafts for a workflow')
    list_parser.add_argument('workflow', help='Workflow name')
    list_parser.add_argument('--json', action='store_true', help='Output as JSON')
    list_parser.add_argument('--workflows-dir', help='Workflow directory')
    list_parser.add_argument('--remote', help='Remote API URL')
    list_parser.add_argument('--token', help='Bearer token for remote mode')
    
    # Diff
    diff_parser = subparsers.add_parser('diff', help='Show diff between drafts or draft vs canonical')
    diff_parser.add_argument('workflow', help='Workflow name')
    diff_parser.add_argument('ts_a', help='First timestamp')
    diff_parser.add_argument('ts_b', nargs='?', help='Second timestamp (optional)')
    diff_parser.add_argument('--workflows-dir', help='Workflow directory')
    diff_parser.add_argument('--remote', help='Remote API URL')
    diff_parser.add_argument('--token', help='Bearer token for remote mode')
    
    # Restore
    restore_parser = subparsers.add_parser('restore', help='Restore a draft as canonical')
    restore_parser.add_argument('workflow', help='Workflow name')
    restore_parser.add_argument('timestamp', help='Draft timestamp')
    restore_parser.add_argument('--yes', action='store_true', help='Skip confirmation')
    restore_parser.add_argument('--workflows-dir', help='Workflow directory')
    restore_parser.add_argument('--remote', help='Remote API URL')
    restore_parser.add_argument('--token', help='Bearer token for remote mode')
    
    # Publish
    publish_parser = subparsers.add_parser('publish', help='Publish a draft (with validation)')
    publish_parser.add_argument('workflow', help='Workflow name')
    publish_parser.add_argument('timestamp', help='Draft timestamp')
    publish_parser.add_argument('--workflows-dir', help='Workflow directory')
    publish_parser.add_argument('--remote', help='Remote API URL')
    publish_parser.add_argument('--token', help='Bearer token for remote mode')
    
    # Delete
    delete_parser = subparsers.add_parser('delete', help='Delete a draft')
    delete_parser.add_argument('workflow', help='Workflow name')
    delete_parser.add_argument('timestamp', help='Draft timestamp')
    delete_parser.add_argument('--yes', action='store_true', help='Skip confirmation')
    delete_parser.add_argument('--workflows-dir', help='Workflow directory')
    delete_parser.add_argument('--remote', help='Remote API URL')
    delete_parser.add_argument('--token', help='Bearer token for remote mode')
    
    args = parser.parse_args(argv)
    
    if not args.subcommand:
        parser.print_help()
        sys.exit(2)
    
    # Dispatch to handler
    if args.subcommand == 'list':
        run_drafts_list(args)
    elif args.subcommand == 'diff':
        run_drafts_diff(args)
    elif args.subcommand == 'restore':
        run_drafts_restore(args)
    elif args.subcommand == 'publish':
        run_drafts_publish(args)
    elif args.subcommand == 'delete':
        run_drafts_delete(args)

#!/usr/bin/env python3
"""
Session Cleanup Hook - Automatic Worktree Cleanup

Triggered at SessionEnd to automatically clean up worktrees for completed issues.

Functionality:
1. Query memory for all worktree-* keys
2. Cross-reference with Jira issue status
3. Delete worktrees for Done/Closed/Cancelled issues
4. Report cleanup summary
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add hooks directory to path for shared utilities
HOOKS_DIR = Path(__file__).parent
sys.path.insert(0, str(HOOKS_DIR))

try:
    from agentdb_client import AgentDBClient, agentdb_request
except ImportError:
    print(json.dumps({"error": "agentdb_client.py not found in hooks directory"}), file=sys.stderr)
    sys.exit(1)


def get_tenant_namespace() -> str:
    """Get tenant namespace from environment"""
    return os.getenv("TENANT_NAMESPACE", "${TENANT_NAMESPACE}")


def get_project_root() -> Path:
    """Get project root directory"""
    project_root = os.getenv("PROJECT_ROOT") or os.getenv("WORKSPACE_ROOT")
    if project_root:
        return Path(project_root)
    # Walk up from cwd looking for sdk/ (project workspace marker)
    d = Path.cwd()
    while d != d.parent:
        if (d / "sdk").is_dir():
            return d
        d = d.parent
    # Probe common workspace layouts under $HOME
    for rel in ("dev/gw", "projects/gw", "${TENANT_NAMESPACE}"):
        candidate = Path.home() / rel
        if (candidate / "sdk").is_dir():
            return candidate
    return Path.home() / "dev" / "${TENANT_NAMESPACE}"


def query_worktree_keys(client: AgentDBClient, namespace: str) -> List[Dict[str, Any]]:
    """Query memory for all worktree-* keys"""
    try:
        # Use recall_query to search for worktree keys
        result = client.recall_query(
            query="worktree",
            namespace=namespace,
            k=100  # Get up to 100 worktree entries
        )

        if not result:
            return []

        # Filter for keys that start with "worktree-"
        worktree_entries = []
        for entry in result:
            key = entry.get("key", "")
            if key.startswith("worktree-"):
                worktree_entries.append(entry)

        return worktree_entries
    except Exception as e:
        print(f"Error querying worktree keys: {e}", file=sys.stderr)
        return []


def get_jira_issue_status(issue_key: str) -> Optional[str]:
    """Get Jira issue status using jira-mcp skill"""
    try:
        skills_dir = Path.home() / ".claude" / "skills" / "jira-mcp"
        get_issue_script = skills_dir / "get_issue.ts"

        if not get_issue_script.exists():
            print(f"Warning: Jira skill not found at {get_issue_script}", file=sys.stderr)
            return None

        # Run the get_issue skill
        cmd = [
            "npx", "tsx", str(get_issue_script),
            json.dumps({
                "issue_key": issue_key,
                "fields": ["status"]
            })
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            print(f"Warning: Failed to get issue {issue_key}: {result.stderr}", file=sys.stderr)
            return None

        # Parse the result
        issue_data = json.loads(result.stdout)
        status = issue_data.get("fields", {}).get("status", {}).get("name")
        return status

    except subprocess.TimeoutExpired:
        print(f"Warning: Timeout getting status for {issue_key}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Warning: Error getting status for {issue_key}: {e}", file=sys.stderr)
        return None


def is_issue_complete(status: Optional[str]) -> bool:
    """Check if issue status indicates completion"""
    if not status:
        return False

    complete_statuses = ["Done", "Closed", "Cancelled", "Resolved"]
    return status in complete_statuses


def remove_worktree(worktree_path: str, repo_path: Path, branch_name: str) -> bool:
    """Remove a worktree and its branch"""
    try:
        # Check if worktree path exists
        worktree_dir = Path(worktree_path)
        if not worktree_dir.exists():
            print(f"Worktree already removed: {worktree_path}", file=sys.stderr)
            return True

        # Navigate to main repo
        os.chdir(repo_path)

        # Remove worktree
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            check=True,
            capture_output=True
        )

        # Prune worktree metadata
        subprocess.run(
            ["git", "worktree", "prune"],
            check=True,
            capture_output=True
        )

        # Delete local branch if it exists
        subprocess.run(
            ["git", "branch", "-D", branch_name],
            capture_output=True  # Don't fail if branch doesn't exist
        )

        print(f"Removed worktree: {worktree_path}", file=sys.stderr)
        return True

    except subprocess.CalledProcessError as e:
        print(f"Error removing worktree {worktree_path}: {e.stderr.decode()}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error removing worktree {worktree_path}: {e}", file=sys.stderr)
        return False


def cleanup_memory_keys(client: AgentDBClient, namespace: str, issue_key: str):
    """Clear memory keys for cleaned up issue"""
    try:
        # Delete worktree key
        client.delete_memory(namespace=namespace, key=f"worktree-{issue_key}")

        # Delete PR key if it exists
        try:
            client.delete_memory(namespace=namespace, key=f"pr-{issue_key}")
        except Exception:
            pass  # PR key might not exist

        print(f"Cleared memory keys for {issue_key}", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Error clearing memory for {issue_key}: {e}", file=sys.stderr)


def cleanup_stale_workflow_state():
    """Delete old workflow-state pattern versions, keeping only the latest per issue key."""
    try:
        result = agentdb_request('POST', '/api/v1/pattern/search', {
            'task': 'workflow-state',
            'k': 100,
            'filters': {'taskType': 'workflow-state'},
        })

        if not result or not result.get('results'):
            return 0

        # Group by issue_key, sort each group by createdAt desc
        by_issue: Dict[str, list] = {}
        for r in result['results']:
            key = (r.get('metadata') or {}).get('issue_key')
            if key:
                by_issue.setdefault(key, []).append(r)

        deleted = 0
        for key, entries in by_issue.items():
            entries.sort(key=lambda e: e.get('createdAt', 0), reverse=True)
            # Keep the newest, delete the rest
            for old in entries[1:]:
                pid = old.get('id')
                if pid is not None:
                    resp = agentdb_request('POST', '/api/v1/pattern/delete', {'pattern_id': str(pid)})
                    if resp:
                        deleted += 1

        if deleted > 0:
            print(f"[session-cleanup] Cleaned {deleted} stale workflow-state pattern(s)", file=sys.stderr)
        return deleted
    except Exception as e:
        print(f"[session-cleanup] Workflow state cleanup error: {e}", file=sys.stderr)
        return 0


def main():
    """Main cleanup logic"""
    # Skip cleanup in subprocess sessions (e.g., Ollama-routed commands)
    if os.environ.get("CLAUDE_SUBPROCESS") == "1":
        print(json.dumps({"skipped": True, "reason": "subprocess session"}))
        return

    try:
        # Clean up stale workflow-state patterns (runs first, independent of worktree cleanup)
        cleanup_stale_workflow_state()

        # Initialize AgentDB client
        client = AgentDBClient()
        namespace = get_tenant_namespace()
        project_root = get_project_root()

        # Query for worktree keys
        worktree_entries = query_worktree_keys(client, namespace)

        if not worktree_entries:
            print(json.dumps({
                "status": "success",
                "message": "No worktrees found in memory",
                "cleaned": 0
            }))
            return

        # Process each worktree
        cleaned_count = 0
        errors = []

        for entry in worktree_entries:
            try:
                key = entry.get("key", "")
                value_str = entry.get("value", "{}")

                # Parse worktree data
                try:
                    worktree_data = json.loads(value_str)
                except json.JSONDecodeError:
                    print(f"Warning: Invalid JSON for key {key}", file=sys.stderr)
                    continue

                issue_key = worktree_data.get("issueKey")
                worktree_path = worktree_data.get("path")
                repo_name = worktree_data.get("repo")
                branch_name = worktree_data.get("branch")

                if not all([issue_key, worktree_path, repo_name, branch_name]):
                    print(f"Warning: Incomplete worktree data for {key}", file=sys.stderr)
                    continue

                # Get Jira issue status
                status = get_jira_issue_status(issue_key)

                # Check if issue is complete
                if is_issue_complete(status):
                    print(f"Cleaning up {issue_key} (status: {status})", file=sys.stderr)

                    # Get repo path
                    repo_path = project_root / repo_name

                    if not repo_path.exists():
                        print(f"Warning: Repository not found: {repo_path}", file=sys.stderr)
                        continue

                    # Remove worktree
                    if remove_worktree(worktree_path, repo_path, branch_name):
                        # Clear memory keys
                        cleanup_memory_keys(client, namespace, issue_key)
                        cleaned_count += 1
                    else:
                        errors.append(f"Failed to remove worktree for {issue_key}")
                else:
                    print(f"Keeping {issue_key} (status: {status})", file=sys.stderr)

            except Exception as e:
                error_msg = f"Error processing worktree {key}: {e}"
                print(error_msg, file=sys.stderr)
                errors.append(error_msg)

        # Return summary
        result = {
            "status": "success",
            "message": f"Cleaned up {cleaned_count} worktree(s)",
            "cleaned": cleaned_count,
            "total_checked": len(worktree_entries),
            "errors": errors
        }

        print(json.dumps(result))

    except Exception as e:
        print(json.dumps({
            "status": "error",
            "message": str(e)
        }), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

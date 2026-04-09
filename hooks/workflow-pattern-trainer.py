#!/usr/bin/env python3
"""
Workflow Pattern Trainer Hook
Captures outcomes from /plan, /groom, /work, /validate, /next commands
and queues them for MCP-based neural pattern learning.

Supports two modes:
1. Local mode (default): Queues patterns to local file for batch processing
2. Central mode (AGENTDB_USE_CENTRAL=true): Syncs to central REST API

Architecture:
- Pre/Post hooks write patterns to a pending queue file
- In central mode, patterns are synced to central AgentDB REST API
- In local mode, patterns are batch-processed via MCP at session start
- Avoids CLI timeout issues by using async queue approach
"""

import json
import sys
import os
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional
import urllib.request
import urllib.error


# Configuration from environment
USE_CENTRAL = os.environ.get('AGENTDB_USE_CENTRAL', 'false').lower() == 'true'
AGENTDB_ENDPOINT = os.environ.get('AGENTDB_ENDPOINT', 'https://YOUR_AGENTDB_URL')
AGENTDB_AUTH_METHOD = os.environ.get('AGENTDB_AUTH_METHOD', 'api-key')
AGENTDB_API_KEY = os.environ.get('AGENTDB_API_KEY', '')

# Pattern storage paths
PATTERN_DIR = Path.home() / ".claude" / "pattern-training"
PATTERN_DIR.mkdir(parents=True, exist_ok=True)

PENDING_PATTERNS = PATTERN_DIR / "pending-patterns.jsonl"
TRAINED_PATTERNS = PATTERN_DIR / "trained-patterns.jsonl"
PATTERN_LOG = PATTERN_DIR / "workflow-patterns.jsonl"

# Central sync queue
SYNC_QUEUE_DIR = Path.home() / '.claude' / 'agentdb-sync-queue'
SYNC_QUEUE_DIR.mkdir(parents=True, exist_ok=True)


# Command to workflow type mappings
COMMAND_WORKFLOW_TYPES = {
    # Core workflow commands
    "work": "implementation",
    "validate": "validation",
    "implement": "implementation",
    "create-implementation-plan": "planning",
    "review": "code_review",
    "fix-pr": "fix",
    "resolve-pr": "merge",
    # Epic lifecycle commands
    "plan": "planning",
    "groom": "grooming",
    "validate-prp": "prp_validation",
    "validate-groom": "groom_validation",
    # Creation commands
    "next": "issue_selection",
    "issue": "issue_creation",
    "bug": "bug_report",
    "change": "change_request",
    # Analysis commands
    "audit": "audit",
    "investigate": "investigation",
    "garden": "backlog_analysis",
    "garden-accuracy": "accuracy_check",
    "garden-cache": "cache_refresh",
    "garden-readiness": "readiness_check",
    "garden-relevancy": "relevancy_check",
    "sequence": "sequencing",
    "sequence-json": "sequencing",
    # Utility commands
    "consolidate-prs": "pr_management",
    "update-docs": "documentation",
    "reclaim": "cleanup",
    "fix-pipeline": "ci_fix",
    # Loop commands
    "loop:issue": "loop_issue",
    "loop:epic": "loop_epic",
    "loop:backlog": "loop_backlog",
    # Metrics commands
    "metrics:baseline": "metrics",
    "metrics:current": "metrics",
    "metrics:compare": "metrics",
    "metrics:report": "metrics",
    "metrics:before-after": "metrics",
}


def get_auth_headers() -> dict:
    """Get authentication headers based on configured auth method."""
    headers = {'Content-Type': 'application/json'}

    if AGENTDB_AUTH_METHOD == 'api-key' and AGENTDB_API_KEY:
        headers['X-Api-Key'] = AGENTDB_API_KEY
    elif AGENTDB_AUTH_METHOD == 'sso':
        try:
            import subprocess
            result = subprocess.run(
                ['aws', 'sts', 'get-caller-identity', '--query', 'Account', '--output', 'text'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                headers['X-AWS-Account'] = result.stdout.strip()
        except Exception:
            pass

    return headers


def call_central_api(endpoint: str, data: dict, timeout: int = 10) -> tuple[bool, Optional[dict]]:
    """Call the central AgentDB REST API."""
    url = f"{AGENTDB_ENDPOINT}{endpoint}"
    headers = get_auth_headers()

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers=headers,
            method='POST'
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status in (200, 201):
                response_data = json.loads(resp.read().decode('utf-8'))
                return True, response_data
            return False, None

    except urllib.error.URLError as e:
        print(f"Network error calling {url}: {e}", file=sys.stderr)
        return False, None
    except urllib.error.HTTPError as e:
        print(f"HTTP error {e.code} calling {url}: {e.reason}", file=sys.stderr)
        return False, None
    except Exception as e:
        print(f"Error calling {url}: {e}", file=sys.stderr)
        return False, None


def store_to_offline_queue(pattern_data: dict) -> Path:
    """Store pattern to offline queue for later sync."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    operation = pattern_data.get('task_type', 'unknown').replace('-', '_')
    queue_file = SYNC_QUEUE_DIR / f"pending_pattern_{operation}_{timestamp}.json"

    with open(queue_file, 'w') as f:
        json.dump({
            "type": "pattern",
            "endpoint": "/api/v1/pattern/store",
            "data": pattern_data,
            "queued_at": datetime.now().isoformat()
        }, f, indent=2)

    return queue_file


def sync_pending_patterns():
    """Attempt to sync any pending pattern queue items to central API."""
    pending_files = sorted(SYNC_QUEUE_DIR.glob('pending_pattern_*.json'))

    if not pending_files:
        return 0

    synced_count = 0
    for queue_file in pending_files:
        try:
            with open(queue_file, 'r') as f:
                queued_item = json.load(f)

            endpoint = queued_item.get('endpoint', '/api/v1/pattern/store')
            data = queued_item.get('data', {})

            success, _ = call_central_api(endpoint, data)
            if success:
                queue_file.unlink()
                synced_count += 1
            else:
                break

        except Exception as e:
            print(f"Error processing queue file {queue_file}: {e}", file=sys.stderr)
            break

    return synced_count


def start_background_sync():
    """Start a background thread to sync pending items."""
    def sync_worker():
        time.sleep(2)
        count = sync_pending_patterns()
        if count > 0:
            print(f"Background sync: {count} patterns synced to central AgentDB")

    thread = threading.Thread(target=sync_worker, daemon=True)
    thread.start()


def save_recovery_context(
    cwd: str,
    operation: str,
    error: str,
    pattern_data: dict
):
    """Save recovery context to docs/recovery/ on failure."""
    recovery_dir = Path(cwd) / 'docs' / 'recovery'
    recovery_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    recovery_file = recovery_dir / f"{timestamp}-pattern-{operation[:20]}.md"

    recovery_content = f"""# Recovery: Pattern Training Sync Failure

**Timestamp:** {datetime.now().isoformat()}
**Operation:** {operation}
**Agent:** workflow-pattern-trainer.py
**Status:** FAILED

## Context
Attempted to store workflow pattern to AgentDB central store.

## Error Details
{error}

## Partial Progress
- [x] Pattern data captured
- [x] Local log updated
- [ ] Sync to central store failed

## Pattern Data
```json
{json.dumps(pattern_data, indent=2)}
```

## Resume Steps
1. Check AGENTDB_ENDPOINT connectivity: `curl {AGENTDB_ENDPOINT}/api/v1/db/health`
2. Verify authentication: Check AGENTDB_API_KEY or AWS SSO credentials
3. Manually sync from queue: Check `~/.claude/agentdb-sync-queue/pending_pattern_*.json`
4. Queue will auto-sync within 60 seconds when endpoint recovers

## AgentDB Context
Queued data stored at: `~/.claude/agentdb-sync-queue/`
"""

    with open(recovery_file, 'w') as f:
        f.write(recovery_content)

    print(f"Recovery context saved to {recovery_file}", file=sys.stderr)
    return recovery_file


def extract_workflow_info(tool_input: dict) -> dict:
    """Extract workflow command and arguments from tool input."""
    command = tool_input.get("command", "")

    workflow_type = None
    issue_key = None
    command_name = None

    # Extract command name and match against known commands
    if command.startswith("/"):
        parts = command.split()
        cmd_part = parts[0][1:]  # Remove leading /

        # Find matching command
        for cmd, wf_type in COMMAND_WORKFLOW_TYPES.items():
            if cmd_part == cmd or cmd_part.startswith(cmd + " "):
                workflow_type = wf_type
                command_name = cmd
                break

        # Extract argument (issue key or other context)
        if len(parts) > 1:
            issue_key = parts[1]

    return {
        "workflow_type": workflow_type,
        "command_name": command_name,
        "issue_key": issue_key,
        "raw_command": command
    }


def log_pattern(pattern_data: dict):
    """Append pattern to history log."""
    pattern_data["logged_at"] = datetime.now().isoformat()
    with open(PATTERN_LOG, "a") as f:
        f.write(json.dumps(pattern_data) + "\n")


def store_pattern_to_central(
    task_type: str,
    approach: str,
    success_rate: float,
    metadata: dict,
    cwd: str
) -> bool:
    """Store pattern to central AgentDB via REST API."""
    pattern_data = {
        "task_type": task_type,
        "approach": approach,
        "success_rate": success_rate,
        "metadata": metadata,
        "tags": [
            f"workflow-{task_type}",
            metadata.get('outcome', 'unknown')
        ]
    }

    success, response = call_central_api('/api/v1/pattern/store', pattern_data)

    if success:
        print(f"Pattern stored to central AgentDB: {response.get('id', 'unknown')}")
        # Try to sync any pending items in background
        start_background_sync()
        return True

    # Central API failed - queue for later sync
    print("Central API unavailable, queuing pattern for later sync", file=sys.stderr)
    queue_file = store_to_offline_queue(pattern_data)
    print(f"Queued to {queue_file}")

    # Save recovery context
    save_recovery_context(
        cwd,
        task_type,
        "Central API unavailable or returned error",
        pattern_data
    )

    return True  # Queued successfully


def queue_pattern_for_training(operation: str, outcome: str, metadata: dict = None):
    """
    Queue a pattern for training.
    In central mode, attempts to sync immediately.
    In local mode, stores in pending-patterns.jsonl for batch processing.
    """
    pattern = {
        "operation": operation,
        "outcome": outcome,
        "metadata": metadata or {},
        "queued_at": datetime.now().isoformat(),
        "status": "pending"
    }

    if USE_CENTRAL:
        # Calculate success rate based on outcome
        success_rate = 0.8 if outcome == "success" else (0.5 if outcome == "partial" else 0.2)
        cwd = metadata.get('cwd', os.getcwd()) if metadata else os.getcwd()

        return store_pattern_to_central(
            task_type=operation,
            approach=f"workflow-{operation}-{outcome}",
            success_rate=success_rate,
            metadata=metadata or {},
            cwd=cwd
        )
    else:
        # Local mode - store to pending patterns file
        with open(PENDING_PATTERNS, "a") as f:
            f.write(json.dumps(pattern) + "\n")
        return True


def get_pending_patterns() -> list:
    """Read all pending patterns from queue."""
    patterns = []
    if PENDING_PATTERNS.exists():
        with open(PENDING_PATTERNS, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        patterns.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return patterns


def mark_patterns_trained(count: int):
    """Move processed patterns from pending to trained."""
    if not PENDING_PATTERNS.exists():
        return

    patterns = get_pending_patterns()

    # Mark first N as trained and move to trained file
    trained = patterns[:count]
    remaining = patterns[count:]

    # Append to trained log
    with open(TRAINED_PATTERNS, "a") as f:
        for p in trained:
            p["status"] = "trained"
            p["trained_at"] = datetime.now().isoformat()
            f.write(json.dumps(p) + "\n")

    # Rewrite pending with remaining
    with open(PENDING_PATTERNS, "w") as f:
        for p in remaining:
            f.write(json.dumps(p) + "\n")


def get_training_stats() -> dict:
    """Get statistics about pattern training."""
    pending = len(get_pending_patterns())

    trained = 0
    if TRAINED_PATTERNS.exists():
        with open(TRAINED_PATTERNS, "r") as f:
            trained = sum(1 for _ in f)

    logged = 0
    if PATTERN_LOG.exists():
        with open(PATTERN_LOG, "r") as f:
            logged = sum(1 for _ in f)

    # Count pending central queue items
    central_pending = len(list(SYNC_QUEUE_DIR.glob('pending_pattern_*.json')))

    return {
        "pending": pending,
        "trained": trained,
        "logged": logged,
        "use_central": USE_CENTRAL,
        "central_pending": central_pending
    }


def handle_pre_tool(tool_input: dict) -> dict:
    """Handle PreToolUse - log start of workflow."""
    workflow_info = extract_workflow_info(tool_input)

    if workflow_info["workflow_type"]:
        pattern_data = {
            "event": "workflow_start",
            "type": workflow_info["workflow_type"],
            "issue": workflow_info["issue_key"],
            "command": workflow_info["raw_command"],
            "phase": "pre"
        }
        log_pattern(pattern_data)

    return {"continue": True}


def handle_post_tool(tool_input: dict, tool_output: dict) -> dict:
    """Handle PostToolUse - capture outcome and queue for training."""
    workflow_info = extract_workflow_info(tool_input)

    if workflow_info["workflow_type"]:
        # Determine success/failure from output
        output_str = str(tool_output.get("output", ""))

        # Heuristics for outcome detection
        success_indicators = [
            "complete", "merged", "validated", "passed", "success",
            "VALIDATION", "DONE", "PR created", "Phase 7", "transitioned to"
        ]
        failure_indicators = [
            "failed", "error", "blocked", "FAILURE", "exception",
            "Anti-Pattern", "AUTOMATIC FAILURE", "timed out"
        ]

        outcome = "partial"
        if any(ind.lower() in output_str.lower() for ind in success_indicators):
            outcome = "success"
        if any(ind.lower() in output_str.lower() for ind in failure_indicators):
            outcome = "failure"

        # Log the pattern
        pattern_data = {
            "event": "workflow_complete",
            "type": workflow_info["workflow_type"],
            "issue": workflow_info["issue_key"],
            "command": workflow_info["raw_command"],
            "outcome": outcome,
            "phase": "post"
        }
        log_pattern(pattern_data)

        # Queue for training (central or local depending on config)
        operation_name = f"workflow-{workflow_info['workflow_type']}"
        queue_pattern_for_training(operation_name, outcome, {
            "issue": workflow_info["issue_key"],
            "command": workflow_info["raw_command"],
            "cwd": os.getcwd()
        })

    return {"continue": True}


def main():
    """Main entry point for hook."""
    # Check for special commands
    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "stats":
            # Output training stats
            stats = get_training_stats()
            print(json.dumps(stats, indent=2))
            return

        elif cmd == "pending":
            # Output pending patterns for MCP processing
            patterns = get_pending_patterns()
            print(json.dumps(patterns, indent=2))
            return

        elif cmd == "mark-trained":
            # Mark N patterns as trained
            count = int(sys.argv[2]) if len(sys.argv) > 2 else 0
            mark_patterns_trained(count)
            print(json.dumps({"marked": count}))
            return

        elif cmd == "sync-pending":
            # Manual trigger to sync pending queue (central mode)
            if USE_CENTRAL:
                count = sync_pending_patterns()
                print(json.dumps({"synced": count}))
            else:
                print("Central mode not enabled (AGENTDB_USE_CENTRAL=false)")
            return

        elif cmd == "queue-status":
            # Show queue status
            local_pending = get_pending_patterns()
            central_pending = list(SYNC_QUEUE_DIR.glob('pending_pattern_*.json'))
            print(json.dumps({
                "use_central": USE_CENTRAL,
                "endpoint": AGENTDB_ENDPOINT,
                "auth_method": AGENTDB_AUTH_METHOD,
                "local_pending_count": len(local_pending),
                "central_pending_count": len(central_pending),
                "central_pending_files": [str(f) for f in central_pending[:10]]
            }, indent=2))
            return

    # Normal hook operation
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps({"continue": True}))
        return

    hook_type = os.environ.get("CLAUDE_HOOK_TYPE", "pre")
    tool_input = input_data.get("tool_input", {})
    tool_output = input_data.get("tool_output", {})

    if hook_type == "pre":
        result = handle_pre_tool(tool_input)
    else:
        result = handle_post_tool(tool_input, tool_output)

    print(json.dumps(result))


if __name__ == "__main__":
    main()

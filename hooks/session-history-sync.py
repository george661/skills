#!/usr/bin/env python3
"""
SessionEnd Hook: Sync session history to AgentDB MCP

This hook runs when a Claude Code session ends and stores the session
transcript as reflexion episodes in AgentDB for cross-session memory.

Supports two modes:
1. Local mode (default): Queues to local file for later sync
2. Central mode (AGENTDB_USE_CENTRAL=true): Syncs to central REST API

Input (via stdin):
{
  "session_id": "abc123",
  "transcript_path": "~/.claude/projects/.../session.jsonl",
  "cwd": "/path/to/project",
  "permission_mode": "default",
  "hook_event_name": "SessionEnd",
  "reason": "exit"
}
"""

import json
import os
import sys
import time
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional
import urllib.request
import urllib.error


# Configuration from environment
USE_CENTRAL = os.environ.get('AGENTDB_USE_CENTRAL', 'false').lower() == 'true'
AGENTDB_ENDPOINT = os.environ.get('AGENTDB_ENDPOINT', 'https://YOUR_AGENTDB_URL')
AGENTDB_AUTH_METHOD = os.environ.get('AGENTDB_AUTH_METHOD', 'api-key')
AGENTDB_API_KEY = os.environ.get('AGENTDB_API_KEY', '')

# Queue directories
SYNC_QUEUE_DIR = Path.home() / '.claude' / 'agentdb-sync-queue'
LOCAL_SYNC_DIR = Path.home() / '.claude' / 'agentdb-sync'

# Ensure directories exist
SYNC_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
LOCAL_SYNC_DIR.mkdir(parents=True, exist_ok=True)


def get_project_name(cwd: str) -> str:
    """Extract project name from working directory."""
    return Path(cwd).name


def parse_transcript(transcript_path: str) -> list[dict]:
    """Parse the JSONL transcript file into messages."""
    messages = []
    path = Path(transcript_path).expanduser()

    if not path.exists():
        return messages

    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return messages


def extract_task_summary(messages: list[dict]) -> str:
    """Extract a summary of what the session accomplished."""
    for msg in messages:
        if msg.get('type') == 'human' or msg.get('role') == 'user':
            content = msg.get('content', '')
            if isinstance(content, str) and content:
                return content[:500] if len(content) > 500 else content
    return "Unknown task"


def extract_outcome(messages: list[dict]) -> str:
    """Extract the outcome/last assistant response."""
    last_response = ""
    for msg in reversed(messages):
        if msg.get('type') == 'ai' or msg.get('role') == 'assistant':
            content = msg.get('content', '')
            if isinstance(content, str) and content:
                last_response = content[:1000] if len(content) > 1000 else content
                break
    return last_response or "Session ended without response"


def count_tool_uses(messages: list[dict]) -> dict:
    """Count tool usage in the session."""
    tool_counts = {}
    for msg in messages:
        tool_calls = msg.get('tool_calls', [])
        if tool_calls:
            for call in tool_calls:
                tool_name = call.get('name', 'unknown')
                tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
    return tool_counts


def estimate_success(messages: list[dict], reason: str) -> bool:
    """Estimate if the session was successful."""
    if reason in ('clear', 'prompt_input_exit', 'exit'):
        return True

    for msg in messages[-5:]:
        content = str(msg.get('content', '')).lower()
        if any(word in content for word in ['error', 'failed', 'exception', 'could not']):
            return False

    return True


def get_auth_headers() -> dict:
    """Get authentication headers based on configured auth method."""
    headers = {'Content-Type': 'application/json'}

    if AGENTDB_AUTH_METHOD == 'api-key' and AGENTDB_API_KEY:
        headers['X-Api-Key'] = AGENTDB_API_KEY
    elif AGENTDB_AUTH_METHOD == 'sso':
        # For SSO, we rely on AWS credentials being available
        # The server will validate via STS GetCallerIdentity
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


def store_to_offline_queue(episode_data: dict, metadata: dict, cwd: str) -> Path:
    """Store episode to offline queue for later sync."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    queue_file = SYNC_QUEUE_DIR / f"pending_{episode_data['session_id']}_{timestamp}.json"

    with open(queue_file, 'w') as f:
        json.dump({
            "type": "reflexion_episode",
            "endpoint": "/api/v1/reflexion/store-episode",
            "data": episode_data,
            "metadata": {
                "project": get_project_name(cwd),
                "cwd": cwd,
                "timestamp": datetime.now().isoformat(),
                "tool_usage": metadata.get('tool_counts', {})
            },
            "queued_at": datetime.now().isoformat()
        }, f, indent=2)

    return queue_file


def store_to_local_sync(episode_data: dict, metadata: dict, cwd: str) -> Path:
    """Store episode to local sync directory (legacy behavior)."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    sync_file = LOCAL_SYNC_DIR / f"episode_{episode_data['session_id']}_{timestamp}.json"

    with open(sync_file, 'w') as f:
        json.dump({
            "type": "reflexion_episode",
            "data": episode_data,
            "metadata": {
                "project": get_project_name(cwd),
                "cwd": cwd,
                "timestamp": datetime.now().isoformat(),
                "tool_usage": metadata.get('tool_counts', {})
            }
        }, f, indent=2)

    return sync_file


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


def sync_pending_queue():
    """Attempt to sync any pending queue items to central API."""
    pending_files = sorted(SYNC_QUEUE_DIR.glob('pending_*.json'))

    if not pending_files:
        return

    synced_count = 0
    for queue_file in pending_files:
        try:
            with open(queue_file, 'r') as f:
                queued_item = json.load(f)

            endpoint = queued_item.get('endpoint', '/api/v1/reflexion/store-episode')
            data = queued_item.get('data', {})

            success, _ = call_central_api(endpoint, data)
            if success:
                queue_file.unlink()
                synced_count += 1
            else:
                # Stop trying if we hit a failure (endpoint may be down)
                break

        except Exception as e:
            print(f"Error processing queue file {queue_file}: {e}", file=sys.stderr)
            break

    if synced_count > 0:
        print(f"Synced {synced_count} pending items to central AgentDB")


def start_background_sync():
    """Start a background thread to sync pending items."""
    def sync_worker():
        # Wait a bit for any startup to settle
        time.sleep(2)
        sync_pending_queue()

    thread = threading.Thread(target=sync_worker, daemon=True)
    thread.start()


def save_recovery_context(
    cwd: str,
    session_id: str,
    error: str,
    task: str,
    partial_data: dict
):
    """Save recovery context to docs/recovery/ on failure."""
    recovery_dir = Path(cwd) / 'docs' / 'recovery'
    recovery_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    recovery_file = recovery_dir / f"{timestamp}-session-{session_id[:8]}.md"

    recovery_content = f"""# Recovery: Session History Sync Failure

**Timestamp:** {datetime.now().isoformat()}
**Session ID:** {session_id}
**Agent:** session-history-sync.py
**Status:** FAILED

## Context
Attempted to sync session history to AgentDB central store.

## Error Details
{error}

## Partial Progress
- [x] Session transcript parsed
- [x] Episode data extracted
- [ ] Sync to central store failed

## Episode Data
```json
{json.dumps(partial_data, indent=2)}
```

## Task Summary
{task[:500] if task else 'Unknown task'}

## Resume Steps
1. Check AGENTDB_ENDPOINT connectivity: `curl {AGENTDB_ENDPOINT}/api/v1/db/health`
2. Verify authentication: Check AGENTDB_API_KEY or AWS SSO credentials
3. Manually sync from queue: Check `~/.claude/agentdb-sync-queue/` for pending items
4. Queue will auto-sync within 60 seconds when endpoint recovers

## AgentDB Context
Queued data stored at: `~/.claude/agentdb-sync-queue/`
"""

    with open(recovery_file, 'w') as f:
        f.write(recovery_content)

    print(f"Recovery context saved to {recovery_file}", file=sys.stderr)
    return recovery_file


def store_episode(
    session_id: str,
    task: str,
    outcome: str,
    success: bool,
    metadata: dict,
    cwd: str
) -> bool:
    """Store the session as a reflexion episode."""
    episode_data = {
        "session_id": session_id,
        "task": task,
        "reward": 0.8 if success else 0.3,
        "success": success,
        "input": task,
        "output": outcome,
        "critique": f"Session in {get_project_name(cwd)} - {metadata.get('reason', 'unknown')} exit",
        "latency_ms": metadata.get('duration_ms', 0),
        "tokens_used": metadata.get('token_count', 0)
    }

    if USE_CENTRAL:
        # Try central API first
        api_success, response = call_central_api(
            '/api/v1/reflexion/store-episode',
            episode_data
        )

        if api_success:
            print(f"Episode stored to central AgentDB: {response.get('id', 'unknown')}")
            # Also try to sync any pending items in background
            start_background_sync()
            return True

        # Central API failed - queue for later sync
        print("Central API unavailable, queuing for later sync", file=sys.stderr)
        queue_file = store_to_offline_queue(episode_data, metadata, cwd)
        print(f"Queued to {queue_file}")

        # Save recovery context
        save_recovery_context(
            cwd,
            session_id,
            "Central API unavailable or returned error",
            task,
            episode_data
        )

        return True  # Queued successfully

    else:
        # Local mode - store to local sync directory
        sync_file = store_to_local_sync(episode_data, metadata, cwd)
        print(f"Episode saved locally: {sync_file}")
        return True


def main():
    """Main hook entry point."""
    # Check for special commands
    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "sync-pending":
            # Manual trigger to sync pending queue
            if USE_CENTRAL:
                sync_pending_queue()
            else:
                print("Central mode not enabled (AGENTDB_USE_CENTRAL=false)")
            return

        elif cmd == "queue-status":
            # Show pending queue status
            pending = list(SYNC_QUEUE_DIR.glob('pending_*.json'))
            print(json.dumps({
                "use_central": USE_CENTRAL,
                "endpoint": AGENTDB_ENDPOINT,
                "auth_method": AGENTDB_AUTH_METHOD,
                "pending_count": len(pending),
                "pending_files": [str(f) for f in pending[:10]]
            }, indent=2))
            return

    # Normal hook operation
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON input: {e}", file=sys.stderr)
        sys.exit(2)

    session_id = input_data.get('session_id', 'unknown')
    transcript_path = input_data.get('transcript_path', '')
    cwd = input_data.get('cwd', os.getcwd())
    reason = input_data.get('reason', 'other')

    # Parse the transcript
    messages = parse_transcript(transcript_path) if transcript_path else []

    if not messages:
        print(f"No transcript to sync for session {session_id}")
        sys.exit(0)

    # Extract session summary
    task = extract_task_summary(messages)
    outcome = extract_outcome(messages)
    tool_counts = count_tool_uses(messages)
    success = estimate_success(messages, reason)

    # Calculate approximate metrics
    message_count = len(messages)

    metadata = {
        'reason': reason,
        'message_count': message_count,
        'tool_counts': tool_counts,
        'duration_ms': 0,
        'token_count': 0
    }

    # Store the episode
    mode = "central" if USE_CENTRAL else "local"
    if store_episode(session_id, task, outcome, success, metadata, cwd):
        print(f"Session {session_id} synced to AgentDB [{mode}] ({message_count} messages)")
    else:
        print(f"Failed to sync session {session_id}", file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()

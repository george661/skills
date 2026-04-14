#!/usr/bin/env python3
"""
PostToolUse:Write|Edit|MultiEdit hook - tracks file edit metrics.

- Writes to local logs for speed
- Async syncs to AgentDB for cross-session learning
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path

# Import agentdb client (optional - fails gracefully)
try:
    from agentdb_client import store_episode_async
    AGENTDB_AVAILABLE = True
except ImportError:
    AGENTDB_AVAILABLE = False


def main():
    # Read hook input from stdin
    try:
        input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}
    except Exception:
        input_data = {}

    tool_input = input_data.get('tool_input', {})
    file_path = tool_input.get('file_path') or tool_input.get('path', '')
    input_data.get('tool_result', {})

    if not file_path:
        print(json.dumps({"continue": True}))
        return

    # Expand path
    file_path = os.path.expanduser(file_path)

    # Get file info after edit
    file_info = {}
    if os.path.exists(file_path):
        try:
            stat = os.stat(file_path)
            file_info = {
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
            }
        except Exception:
            pass

    # Log edit metrics
    log_dir = os.path.expanduser('~/.claude/logs')
    os.makedirs(log_dir, exist_ok=True)

    metrics_file = os.path.join(log_dir, 'edit-metrics.jsonl')

    metric_entry = {
        'timestamp': datetime.now().isoformat(),
        'file': file_path,
        'extension': Path(file_path).suffix.lower(),
        'directory': os.path.dirname(file_path),
        'file_size': file_info.get('size', 0),
        'success': True  # If we got here, the edit succeeded
    }

    try:
        with open(metrics_file, 'a') as f:
            f.write(json.dumps(metric_entry) + '\n')
    except Exception as e:
        print(f"[post-edit] Failed to log metrics: {e}", file=sys.stderr)

    # Async sync to AgentDB (fire and forget)
    if AGENTDB_AVAILABLE:
        try:
            namespace = os.environ.get('TENANT_NAMESPACE', 'hooks')
            session_id = os.environ.get('CLAUDE_SESSION_ID', 'unknown')
            ext = Path(file_path).suffix.lower()
            store_episode_async(
                session_id=session_id,
                task=f"edit:{ext}:{Path(file_path).name[:30]}",
                reward=1.0,  # Edit succeeded
                success=True,
                trajectory=[{
                    'action': 'edit',
                    'file_extension': ext,
                    'file_size': file_info.get('size', 0),
                    'directory': os.path.dirname(file_path)[:100]
                }],
                namespace=namespace
            )
        except Exception:
            pass  # Don't block on AgentDB failures

    # Output success
    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()

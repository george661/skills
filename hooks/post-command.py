#!/usr/bin/env python3
"""
PostToolUse:Bash hook - tracks command execution metrics.

- Writes to local logs for speed
- Async syncs to AgentDB for cross-session learning
"""

import json
import sys
import os
from datetime import datetime

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
    except:
        input_data = {}

    command = input_data.get('tool_input', {}).get('command', '')
    tool_result = input_data.get('tool_result', {})

    # Extract result info
    exit_code = 0
    output_length = 0

    if isinstance(tool_result, dict):
        # Check for error indicators
        if tool_result.get('error') or 'error' in str(tool_result).lower()[:100]:
            exit_code = 1
        output_length = len(str(tool_result))
    elif isinstance(tool_result, str):
        output_length = len(tool_result)
        if 'error' in tool_result.lower()[:100]:
            exit_code = 1

    # Log to metrics file
    log_dir = os.path.expanduser('~/.claude/logs')
    os.makedirs(log_dir, exist_ok=True)

    metrics_file = os.path.join(log_dir, 'command-metrics.jsonl')

    metric_entry = {
        'timestamp': datetime.now().isoformat(),
        'command': command[:200] if command else '',  # Truncate long commands
        'exit_code': exit_code,
        'output_length': output_length,
        'success': exit_code == 0
    }

    try:
        with open(metrics_file, 'a') as f:
            f.write(json.dumps(metric_entry) + '\n')
    except Exception as e:
        print(f"[post-command] Failed to log metrics: {e}", file=sys.stderr)

    # Async sync to AgentDB (fire and forget)
    if AGENTDB_AVAILABLE:
        try:
            namespace = os.environ.get('TENANT_NAMESPACE', 'hooks')
            session_id = os.environ.get('CLAUDE_SESSION_ID', 'unknown')
            store_episode_async(
                session_id=session_id,
                task=f"command:{command[:50]}",
                reward=1.0 if exit_code == 0 else 0.0,
                success=exit_code == 0,
                trajectory=[{
                    'action': 'bash',
                    'command': command[:200],
                    'exit_code': exit_code,
                    'output_length': output_length
                }],
                namespace=namespace
            )
        except:
            pass  # Don't block on AgentDB failures

    # Output success
    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()

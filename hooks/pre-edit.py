#!/usr/bin/env python3
"""
PreToolUse:Write|Edit|MultiEdit hook - validates file edits and loads context.

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
    from agentdb_client import store_pattern_async
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

    if not file_path:
        print(json.dumps({"continue": True}))
        return

    # Expand path
    file_path = os.path.expanduser(file_path)

    # Check file context
    context = {}
    if os.path.exists(file_path):
        try:
            stat = os.stat(file_path)
            context = {
                'exists': True,
                'size': stat.st_size,
                'is_directory': os.path.isdir(file_path)
            }
        except Exception:
            context = {'exists': True}
    else:
        context = {
            'exists': False,
            'will_create': True,
            'directory': os.path.dirname(file_path)
        }

    # Suggest agent type based on file extension
    ext = Path(file_path).suffix.lower()
    agent_mapping = {
        '.js': 'javascript-developer',
        '.ts': 'typescript-developer',
        '.tsx': 'typescript-developer',
        '.py': 'python-developer',
        '.go': 'golang-developer',
        '.rs': 'rust-developer',
        '.java': 'java-developer',
        '.md': 'technical-writer',
        '.yaml': 'devops-engineer',
        '.yml': 'devops-engineer',
        '.json': 'config-specialist',
        '.sql': 'database-expert',
        '.sh': 'system-admin',
    }

    suggested_agent = agent_mapping.get(ext, 'general-developer')

    # Log pre-edit info
    log_dir = os.path.expanduser('~/.claude/logs')
    os.makedirs(log_dir, exist_ok=True)

    # Async sync to AgentDB (fire and forget)
    if AGENTDB_AVAILABLE:
        try:
            namespace = os.environ.get('TENANT_NAMESPACE', 'hooks')
            store_pattern_async(
                task_type='pre-edit',
                pattern={
                    'file_extension': ext,
                    'suggested_agent': suggested_agent,
                    'file_exists': context.get('exists', False),
                    'file_size': context.get('size', 0),
                    'timestamp': datetime.now().isoformat()
                },
                namespace=namespace
            )
        except Exception:
            pass  # Don't block on AgentDB failures

    # Output success with context
    result = {
        "continue": True,
        "context": context,
        "suggested_agent": suggested_agent
    }

    print(json.dumps(result))


if __name__ == "__main__":
    main()

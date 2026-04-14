#!/usr/bin/env python3
"""
PreToolUse:Bash hook - validates command safety before execution.

- Writes to local logs for speed
- Async syncs to AgentDB for cross-session learning
"""

import json
import sys
import os
from datetime import datetime

# Import agentdb client (optional - fails gracefully)
try:
    from agentdb_client import store_pattern_async
    AGENTDB_AVAILABLE = True
except ImportError:
    AGENTDB_AVAILABLE = False

# Dangerous command patterns
DANGEROUS_PATTERNS = [
    'rm -rf /',
    'rm -rf .',
    'rm -rf *',
    'format ',
    'fdisk ',
    'mkfs ',
    '| bash',
    '| sh',
    'chmod 777',
    ':(){:|:&};:',  # Fork bomb
]


def main():
    # Read hook input from stdin
    try:
        input_data = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}
    except Exception:
        input_data = {}

    command = input_data.get('tool_input', {}).get('command', '')

    if not command:
        print(json.dumps({"continue": True}))
        return

    # Intercept raw `fly` CLI calls — redirect to fly skill which handles auth automatically
    command_stripped = command.strip()
    if (command_stripped.startswith('fly ') or command_stripped.startswith('fly\t')) and 'npx tsx' not in command:
        print(json.dumps({
            "decision": "block",
            "reason": (
                "Use the fly skills instead of the raw `fly` CLI. "
                "The fly skills auto-authenticate via AWS Secrets Manager.\n\n"
                "Examples:\n"
                "  npx tsx ~/.claude/skills/fly/list_builds.ts '{\"pipeline\": \"lambda-functions\"}'\n"
                "  npx tsx ~/.claude/skills/fly/list_pipelines.ts '{}'\n"
                "  npx tsx ~/.claude/skills/fly/trigger_job.ts '{\"pipeline\": \"lambda-functions\", \"job\": \"<job>\"}'\n"
                "  npx tsx ~/.claude/skills/fly/login.ts '{}'\n\n"
                "Available fly skills: login, list_builds, list_pipelines, get_pipeline, "
                "trigger_job, watch_build, abort_build, set_pipeline, validate_pipeline, "
                "workers, containers, prune_worker, land_worker"
            )
        }))
        return

    # Block creating NEW work in deprecated api-service (allow reads, logs, diffs, etc.)
    if 'api-service' in command:
        new_work_patterns = ['worktree add', 'checkout -b', 'branch -b', 'switch -c']
        if any(p in command for p in new_work_patterns):
            print(json.dumps({
                "decision": "block",
                "reason": (
                    "api-service is DEPRECATED. New work should target:\n"
                    "  - lambda-functions: Lambda functions (70+ across 14 domains)\n"
                    "  - core-infra: Infrastructure (DynamoDB, S3, VPC, IAM, API Gateway, CloudWatch)\n"
                    "  - go-common: Shared Go packages (models, response, auth, middleware)\n\n"
                    "Check project-docs/domain/ for the domain model and bounded context mappings."
                )
            }))
            return

    # Check for dangerous commands
    command_lower = command.lower()
    is_dangerous = False
    matched_pattern = None

    for pattern in DANGEROUS_PATTERNS:
        if pattern.lower() in command_lower:
            is_dangerous = True
            matched_pattern = pattern
            print(f"[pre-command] Warning: potentially dangerous pattern '{pattern}'", file=sys.stderr)
            break

    # Log to local file
    log_dir = os.path.expanduser('~/.claude/logs')
    os.makedirs(log_dir, exist_ok=True)

    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'command': command[:500],  # Truncate
        'dangerous': is_dangerous,
        'matched_pattern': matched_pattern
    }

    try:
        with open(os.path.join(log_dir, 'pre-command.jsonl'), 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    except Exception:
        pass

    # Async sync to AgentDB (fire and forget)
    if AGENTDB_AVAILABLE:
        try:
            # Get tenant namespace from environment
            namespace = os.environ.get('TENANT_NAMESPACE', 'hooks')
            store_pattern_async(
                task_type='pre-command',
                pattern={
                    'command_prefix': command[:50],
                    'dangerous': is_dangerous,
                    'timestamp': datetime.now().isoformat()
                },
                namespace=namespace
            )
        except Exception:
            pass  # Don't block on AgentDB failures

    # Output success - allow command to proceed (even dangerous ones - just warn)
    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()

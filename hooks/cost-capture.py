#!/usr/bin/env python3
"""
Cost Capture Hook
Captures session costs after /work and /validate commands complete.
- Appends to ~/.claude/output/costs.jsonl for local analysis
- Stores to AgentDB for cross-session analysis and comparison

Usage:
  - Runs automatically via PostToolUse hook on SlashCommand
  - Manual: python3 ~/.claude/hooks/cost-capture.py <issue> <command>
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path
from glob import glob

# Import AgentDB client for central storage
try:
    from agentdb_client import store_pattern_async, agentdb_request
    AGENTDB_AVAILABLE = True
except ImportError:
    AGENTDB_AVAILABLE = False

# Paths - hooks are installed to ~/.claude/hooks/
# Output goes to ~/.claude/output/ (consistent with global architecture)
def get_output_dir() -> Path:
    """Get output directory - ~/.claude/output/ for global installation."""
    # Check for workspace (Docker) first
    if Path("/workspace/output").exists() or Path("/workspace").exists():
        return Path("/workspace/output")
    # Default: ~/.claude/output/ (matches global hook architecture)
    return Path.home() / ".claude" / "output"

OUTPUT_DIR = get_output_dir()
COSTS_FILE = OUTPUT_DIR / "costs.jsonl"
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"

# Commands to capture costs for - ALL agents commands
TRACKED_COMMANDS = [
    # Core workflow commands
    "work", "validate", "implement", "create-implementation-plan",
    "review", "fix-pr", "resolve-pr",
    # Epic lifecycle commands
    "plan", "groom", "validate-prp", "validate-groom",
    # Creation commands
    "next", "issue", "bug", "change",
    # Analysis commands
    "audit", "investigate", "garden", "garden-accuracy",
    "garden-cache", "garden-readiness", "garden-relevancy",
    "sequence", "sequence-json",
    # Utility commands
    "consolidate-prs", "update-docs", "reclaim", "fix-pipeline",
    # Loop commands
    "loop:issue", "loop:epic", "loop:backlog",
    # Metrics commands
    "metrics:baseline", "metrics:current", "metrics:compare",
    "metrics:report", "metrics:before-after",
]

# Model pricing (per 1M tokens)
MODEL_PRICING = {
    'claude-opus-4-6': {'input': 15.0, 'output': 75.0, 'cache_read': 1.5, 'cache_write': 18.75},
    'claude-opus-4-5-20251101': {'input': 15.0, 'output': 75.0, 'cache_read': 1.5, 'cache_write': 18.75},
    'claude-sonnet-4-5-20250929': {'input': 3.0, 'output': 15.0, 'cache_read': 0.3, 'cache_write': 3.75},
    'claude-sonnet-4-20250514': {'input': 3.0, 'output': 15.0, 'cache_read': 0.3, 'cache_write': 3.75},
    'claude-3-5-sonnet-20241022': {'input': 3.0, 'output': 15.0, 'cache_read': 0.3, 'cache_write': 3.75},
    'claude-haiku-4-5-20251001': {'input': 0.80, 'output': 4.0, 'cache_read': 0.08, 'cache_write': 1.0},
    'default': {'input': 3.0, 'output': 15.0, 'cache_read': 0.3, 'cache_write': 3.75},
}


def find_current_session() -> Path | None:
    """Find the most recently modified conversation file."""
    if not CLAUDE_PROJECTS.exists():
        return None

    jsonl_files = list(CLAUDE_PROJECTS.rglob("*.jsonl"))
    # Filter out agent files
    jsonl_files = [f for f in jsonl_files if not f.name.startswith('agent-')]

    if not jsonl_files:
        return None

    return max(jsonl_files, key=lambda f: f.stat().st_mtime)


def calculate_cost(usage: dict, model: str = 'default') -> float:
    """Calculate cost from usage stats."""
    if not usage or not isinstance(usage, dict):
        return 0.0

    pricing = MODEL_PRICING.get(model, MODEL_PRICING['default'])

    return (
        (usage.get('input_tokens', 0) / 1_000_000) * pricing['input'] +
        (usage.get('output_tokens', 0) / 1_000_000) * pricing['output'] +
        (usage.get('cache_read_input_tokens', 0) / 1_000_000) * pricing['cache_read'] +
        (usage.get('cache_creation_input_tokens', 0) / 1_000_000) * pricing['cache_write']
    )


def extract_session_cost(session_file: Path) -> dict:
    """Extract cost from session file."""
    total_cost = 0.0
    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_write = 0
    model_used = 'default'
    first_ts = None
    last_ts = None

    try:
        with open(session_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())

                    ts = entry.get('timestamp')
                    if ts:
                        if not first_ts:
                            first_ts = ts
                        last_ts = ts

                    if entry.get('type') == 'assistant':
                        message = entry.get('message', {})
                        usage = message.get('usage', {})
                        if usage:
                            model_used = message.get('model', 'default')
                            total_input += usage.get('input_tokens', 0)
                            total_output += usage.get('output_tokens', 0)
                            total_cache_read += usage.get('cache_read_input_tokens', 0)
                            total_cache_write += usage.get('cache_creation_input_tokens', 0)
                            total_cost += calculate_cost(usage, model_used)
                except:
                    continue
    except Exception as e:
        return {}

    return {
        'cost_usd': round(total_cost, 4),
        'tokens': {
            'input': total_input,
            'output': total_output,
            'cache_read': total_cache_read,
            'cache_write': total_cache_write,
            'total': total_input + total_output + total_cache_read + total_cache_write
        },
        'model': model_used,
        'session_file': session_file.name,
        'first_timestamp': first_ts,
        'last_timestamp': last_ts
    }


def extract_command_info(tool_input: dict) -> tuple[str, str] | None:
    """Extract command type and issue key/context from tool input."""
    command = tool_input.get("command", "")

    for tracked in TRACKED_COMMANDS:
        if command.startswith(f"/{tracked}"):
            parts = command.split()
            # Extract argument (issue key or other context)
            if len(parts) > 1:
                arg = parts[1].upper()
            else:
                # For commands without arguments, use command name as context
                arg = tracked.upper().replace(":", "-").replace("-", "_")
            return (tracked, arg)

    return None


def store_cost_in_agentdb(cost_record: dict) -> bool:
    """Store cost record in AgentDB for cross-session analysis."""
    if not AGENTDB_AVAILABLE:
        return False

    try:
        # Get namespace from environment or use default
        namespace = os.environ.get('TENANT_NAMESPACE', 'costs')

        # Build approach description for AgentDB pattern format
        issue = cost_record.get('issue', 'unknown')
        command = cost_record.get('command', 'unknown')
        cost = cost_record.get('cost_usd', 0)
        model = cost_record.get('model', 'unknown')
        approach = f"Session cost: {command} on {issue} - ${cost:.2f} using {model}"

        # Store as a pattern with task_type 'session-cost'
        # AgentDB requires: task_type, approach, success_rate, and optional pattern/metadata
        store_pattern_async(
            task_type='session-cost',
            pattern={
                'approach': approach,
                'success_rate': 1.0,  # Cost capture always succeeds
                'metadata': {
                    'issue': issue,
                    'command': command,
                    'cost_usd': cost_record.get('cost_usd'),
                    'tokens': cost_record.get('tokens'),
                    'model': model,
                    'session_file': cost_record.get('session_file'),
                    'captured_at': cost_record.get('captured_at'),
                    'session_start': cost_record.get('session_start'),
                    'session_end': cost_record.get('session_end'),
                }
            },
            namespace=namespace
        )
        return True
    except Exception as e:
        print(f"[cost-capture] AgentDB storage error: {e}", file=sys.stderr)
        return False


def capture_cost(issue_key: str, command: str):
    """Capture cost for an issue/command and append to costs.jsonl."""
    session_file = find_current_session()
    if not session_file:
        return {"error": "No session file found"}

    session_data = extract_session_cost(session_file)
    if not session_data:
        return {"error": "Could not extract session data"}

    # Build cost record
    cost_record = {
        'issue': issue_key,
        'command': command,
        'cost_usd': session_data['cost_usd'],
        'tokens': session_data['tokens'],
        'model': session_data['model'],
        'session_file': session_data['session_file'],
        'captured_at': datetime.now().isoformat(),
        'session_start': session_data.get('first_timestamp'),
        'session_end': session_data.get('last_timestamp')
    }

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Append to local costs.jsonl
    with open(COSTS_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(cost_record) + '\n')

    # 2. Store in AgentDB for cross-session analysis (async, non-blocking)
    agentdb_stored = store_cost_in_agentdb(cost_record)

    return {
        "captured": True,
        "issue": issue_key,
        "command": command,
        "cost_usd": cost_record['cost_usd'],
        "tokens": cost_record['tokens']['total'],
        "agentdb": agentdb_stored
    }


def handle_post_tool(tool_input: dict) -> dict:
    """Handle PostToolUse for SlashCommand."""
    cmd_info = extract_command_info(tool_input)

    if cmd_info:
        command, issue_key = cmd_info
        result = capture_cost(issue_key, command)
        # Log to stderr (won't interfere with JSON output)
        print(f"Cost captured: {issue_key} {command} ${result.get('cost_usd', 0):.2f}", file=sys.stderr)
        return {"continue": True, "cost_captured": result}

    return {"continue": True}


def main():
    """Main entry point."""
    # Manual invocation: python3 cost-capture.py <issue> <command>
    if len(sys.argv) >= 3:
        issue_key = sys.argv[1].upper()
        command = sys.argv[2].lower()
        result = capture_cost(issue_key, command)
        print(json.dumps(result, indent=2))
        return

    # Hook invocation via stdin
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps({"continue": True}))
        return

    tool_input = input_data.get("tool_input", {})
    result = handle_post_tool(tool_input)
    print(json.dumps(result))


if __name__ == "__main__":
    main()

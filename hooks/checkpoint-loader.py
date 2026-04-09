#!/usr/bin/env python3
"""
Checkpoint Loader Hook (PreToolUse)

Automatically loads checkpoints from AgentDB at the start of commands,
enabling seamless resume of interrupted workflows.

Usage:
  - Runs automatically via PreToolUse hook on SlashCommand
  - Manual: python3 checkpoint-loader.py <issue> [phase]
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

# Import AgentDB client
try:
    from agentdb_client import agentdb_request, get_credentials, validate_issue_key, get_namespace
    AGENTDB_AVAILABLE = True
except ImportError:
    AGENTDB_AVAILABLE = False

    # Fallback validation if agentdb_client not available
    import re

    def validate_issue_key(issue_key: str) -> str:
        if not issue_key or not re.match(r'^[A-Za-z0-9_-]+$', issue_key):
            raise ValueError(f"Invalid issue key: {issue_key}")
        return issue_key.upper()

    def get_namespace() -> str:
        return os.environ.get('TENANT_NAMESPACE', 'default')

NAMESPACE = get_namespace() if AGENTDB_AVAILABLE else os.environ.get('TENANT_NAMESPACE', 'default')

# Commands that should check for existing checkpoints
RESUMABLE_COMMANDS = [
    "work", "implement", "review", "fix-pr", "resolve-pr", "validate",
    "plan", "groom", "fix-prp", "fix-groom",
    "loop:issue", "loop:epic",
]

# Map commands to their expected checkpoint phases
COMMAND_TO_PHASE = {
    'work': ['planning', 'implementing', 'reviewing', 'fixing', 'merging', 'validating'],
    'implement': ['planning', 'implementing'],
    'review': ['implementing', 'reviewing'],
    'fix-pr': ['reviewing', 'fixing'],
    'resolve-pr': ['fixing', 'merging'],
    'validate': ['merging', 'validating'],
    'plan': ['epic-planning'],
    'groom': ['epic-planning', 'grooming'],
    'fix-prp': ['epic-planning'],
    'fix-groom': ['grooming'],
    'loop:issue': ['planning', 'implementing', 'reviewing', 'fixing', 'merging', 'validating'],
}


def extract_command_info(tool_input: dict) -> Optional[Tuple[str, str]]:
    """Extract command type and issue key from tool input."""
    command = tool_input.get("command", "")

    for tracked in RESUMABLE_COMMANDS:
        if command.startswith(f"/{tracked}"):
            parts = command.split()
            if len(parts) > 1:
                arg = parts[1].upper()
            else:
                arg = None
            return (tracked, arg)

    return None


def load_checkpoint_from_agentdb(issue: str, phases: list) -> Optional[Dict[str, Any]]:
    """
    Load the most recent checkpoint for an issue from AgentDB.
    Checkpoints are stored as one pattern per issue with a 'phases' dict in metadata.
    """
    if not AGENTDB_AVAILABLE:
        return None

    try:
        creds = get_credentials()
        if not creds.get('apiKey'):
            return None

        result = agentdb_request('POST', '/api/v1/pattern/search', {
            'task': f"checkpoint {issue}",
            'k': 10,
            'filters': {'taskType': 'checkpoint'},
        })

        if not result:
            return None

        hits = result.get('results', [])
        if not hits:
            return None

        # Find the issue's state (most recent non-deleted)
        for hit in sorted(hits, key=lambda h: h.get('createdAt', 0), reverse=True):
            metadata = hit.get('metadata', {})
            if metadata.get('deleted'):
                continue
            if metadata.get('issue') != issue:
                continue

            # Look through stored phases for a match (reverse order = most recent phase first)
            stored_phases = metadata.get('phases', {})
            for target_phase in reversed(phases):
                if target_phase in stored_phases:
                    cp = stored_phases[target_phase]
                    return {
                        'found': True,
                        'issue': issue,
                        'phase': target_phase,
                        'data': cp.get('data', {}),
                        'timestamp': cp.get('timestamp'),
                        'age_hours': _calculate_age(cp.get('timestamp')),
                        'source': 'agentdb'
                    }

            return None  # Found the issue but no matching phase

        return None

    except Exception as e:
        print(f"[checkpoint-loader] Error loading from AgentDB: {e}", file=sys.stderr)
        return None


def load_checkpoint_from_filesystem(issue: str, phases: list) -> Optional[Dict[str, Any]]:
    """Fall back to filesystem checkpoints if AgentDB unavailable."""
    checkpoint_dir = Path(os.environ.get('CHECKPOINT_DIR', os.path.expanduser('~/.claude/checkpoints')))

    if not checkpoint_dir.exists():
        return None

    safe_issue = issue.replace('/', '-').replace('\\', '-')

    # Check phases in reverse order
    for phase in reversed(phases):
        checkpoint_path = checkpoint_dir / f"{safe_issue}-{phase}.json"
        if checkpoint_path.exists():
            try:
                with open(checkpoint_path) as f:
                    checkpoint = json.load(f)
                return {
                    'found': True,
                    'issue': issue,
                    'phase': phase,
                    'data': checkpoint.get('data', {}),
                    'timestamp': checkpoint.get('timestamp'),
                    'age_hours': _calculate_age(checkpoint.get('timestamp')),
                    'source': 'filesystem'
                }
            except (json.JSONDecodeError, KeyError, IOError) as e:
                print(f"[checkpoint-loader] Error reading checkpoint {checkpoint_path}: {e}", file=sys.stderr)
                continue

    return None


def _calculate_age(timestamp_str: str) -> float:
    """Calculate age in hours from ISO timestamp."""
    if not timestamp_str:
        return 0.0
    try:
        ts = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        age = datetime.now(ts.tzinfo) - ts if ts.tzinfo else datetime.now() - ts
        return round(age.total_seconds() / 3600, 2)
    except (ValueError, TypeError) as e:
        print(f"[checkpoint-loader] Error parsing timestamp '{timestamp_str}': {e}", file=sys.stderr)
        return 0.0


def load_checkpoint(issue: str, command: str) -> Dict[str, Any]:
    """
    Load checkpoint for an issue, trying AgentDB first then filesystem.
    """
    phases = COMMAND_TO_PHASE.get(command, [])

    if not phases:
        return {'found': False, 'reason': 'command_not_resumable'}

    # 1. Try AgentDB first
    checkpoint = load_checkpoint_from_agentdb(issue, phases)
    if checkpoint:
        return checkpoint

    # 2. Fall back to filesystem
    checkpoint = load_checkpoint_from_filesystem(issue, phases)
    if checkpoint:
        return checkpoint

    return {'found': False, 'issue': issue, 'phases_checked': phases}


def handle_pre_tool(tool_input: dict) -> dict:
    """Handle PreToolUse for SlashCommand."""
    cmd_info = extract_command_info(tool_input)

    if cmd_info:
        command, issue_key = cmd_info

        if issue_key:
            checkpoint = load_checkpoint(issue_key, command)

            if checkpoint.get('found'):
                phase = checkpoint.get('phase')
                source = checkpoint.get('source')
                age = checkpoint.get('age_hours', 0)
                print(f"[checkpoint] Found {issue_key} at {phase} ({age:.1f}h ago, {source})", file=sys.stderr)

                # Return checkpoint data to be available in the command context
                return {
                    "continue": True,
                    "checkpoint_loaded": checkpoint,
                    "message": f"Resuming {issue_key} from {phase} phase"
                }

    return {"continue": True}


def main():
    """Main entry point."""
    # Manual invocation: python3 checkpoint-loader.py <issue> [command]
    if len(sys.argv) >= 2:
        issue_key = sys.argv[1].upper()
        command = sys.argv[2].lower() if len(sys.argv) > 2 else 'work'
        result = load_checkpoint(issue_key, command)
        print(json.dumps(result, indent=2))
        return

    # Hook invocation via stdin
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps({"continue": True}))
        return

    tool_input = input_data.get("tool_input", {})
    result = handle_pre_tool(tool_input)
    print(json.dumps(result))


if __name__ == "__main__":
    main()

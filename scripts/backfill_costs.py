#!/usr/bin/env python3
"""
Backfill Cost Data from Conversation History

Scans Claude conversation history files to extract cost data for commands
that weren't being tracked (plan, groom, validate-plan, fix-plan, validate-groom).

Usage:
  python3 scripts/backfill_costs.py                    # Dry run (show what would be added)
  python3 scripts/backfill_costs.py --apply            # Apply changes to costs.jsonl
  python3 scripts/backfill_costs.py --since 2026-01-08 # Only process files after date
"""

import json
import sys
import os
import re
import argparse
from datetime import datetime
from pathlib import Path
from glob import glob

# Paths
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
COSTS_FILE = OUTPUT_DIR / "costs.jsonl"

# Commands to backfill (ones that weren't being tracked)
BACKFILL_COMMANDS = [
    "plan", "groom", "validate-plan", "fix-plan", "validate-groom",
    # Legacy aliases (for backward compatibility with historical data)
    "validate-prp", "fix-prp",
    "create-implementation-plan", "implement", "review", "fix-pr", "resolve-pr",
    "next", "issue", "bug", "change",
    "audit", "investigate", "garden", "garden-accuracy",
    "garden-cache", "garden-readiness", "garden-relevancy",
    "sequence", "sequence-json",
    "consolidate-prs", "update-docs", "reclaim", "fix-pipeline",
    "loop-issue", "loop-epic", "loop-backlog",
    "loop:issue", "loop:epic", "loop:backlog",
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


def load_existing_costs() -> set:
    """Load existing cost records to avoid duplicates."""
    existing = set()
    if COSTS_FILE.exists():
        with open(COSTS_FILE, 'r') as f:
            for line in f:
                try:
                    record = json.loads(line)
                    # Create unique key: session_file + command + issue
                    key = f"{record.get('session_file', '')}:{record.get('command', '')}:{record.get('issue', '')}"
                    existing.add(key)
                except:
                    continue
    return existing


def extract_command_from_message(content: str) -> tuple[str, str] | None:
    """Extract command name and argument from user message content."""
    # Pattern: <command-name>/command</command-name>\n<command-args>ARG</command-args>
    cmd_match = re.search(r'<command-name>/([a-z:-]+)</command-name>', content)
    arg_match = re.search(r'<command-args>([^<]*)</command-args>', content)

    if cmd_match:
        command = cmd_match.group(1)
        if command in BACKFILL_COMMANDS:
            arg = arg_match.group(1).strip().upper() if arg_match else command.upper().replace(":", "-").replace("-", "_")
            # Truncate long arguments (keep just the issue key if it looks like one)
            if len(arg) > 50:
                # Try to extract just the issue key (PROJ-XXX pattern)
                issue_match = re.search(r'(PROJ-\d+)', arg)
                if issue_match:
                    arg = issue_match.group(1)
                else:
                    arg = arg[:47] + "..."
            return (command, arg)

    return None


def process_session_file(session_file: Path) -> dict | None:
    """Process a session file and extract command cost data."""
    commands_found = []
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

                    # Look for command invocations in user messages
                    if entry.get('type') == 'user':
                        msg = entry.get('message', {})
                        content = msg.get('content', '')
                        if isinstance(content, str):
                            cmd_info = extract_command_from_message(content)
                            if cmd_info:
                                commands_found.append(cmd_info)

                    # Accumulate token usage from assistant messages
                    if entry.get('type') == 'assistant':
                        msg = entry.get('message', {})
                        usage = msg.get('usage', {})
                        if usage:
                            model_used = msg.get('model', 'default')
                            total_input += usage.get('input_tokens', 0)
                            total_output += usage.get('output_tokens', 0)
                            total_cache_read += usage.get('cache_read_input_tokens', 0)
                            total_cache_write += usage.get('cache_creation_input_tokens', 0)
                except:
                    continue
    except Exception as e:
        return None

    if not commands_found:
        return None

    # Calculate total cost
    usage = {
        'input_tokens': total_input,
        'output_tokens': total_output,
        'cache_read_input_tokens': total_cache_read,
        'cache_creation_input_tokens': total_cache_write
    }
    total_cost = calculate_cost(usage, model_used)

    # Return data for each command found
    return {
        'commands': commands_found,
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


def find_project_sessions(since_date: str = None) -> list[Path]:
    """Find all project session files."""
    sessions = []

    # Search in project directories under Claude projects
    project_patterns = [
        CLAUDE_PROJECTS / "*" / "*.jsonl",
    ]

    for pattern in project_patterns:
        for f in glob(str(pattern)):
            path = Path(f)
            # Skip agent files
            if path.name.startswith('agent-'):
                continue
            # Skip subagent directories
            if 'subagents' in str(path):
                continue

            # Filter by date if specified
            if since_date:
                try:
                    file_mtime = datetime.fromtimestamp(path.stat().st_mtime)
                    filter_date = datetime.strptime(since_date, '%Y-%m-%d')
                    if file_mtime < filter_date:
                        continue
                except:
                    pass

            sessions.append(path)

    return sessions


def main():
    parser = argparse.ArgumentParser(description='Backfill cost data from conversation history')
    parser.add_argument('--apply', action='store_true', help='Apply changes (default is dry run)')
    parser.add_argument('--since', type=str, help='Only process files modified since date (YYYY-MM-DD)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()

    print("=" * 60)
    print("COST DATA BACKFILL")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    if args.since:
        print(f"Since: {args.since}")
    print("=" * 60)

    # Load existing costs to avoid duplicates
    existing = load_existing_costs()
    print(f"\nExisting cost records: {len(existing)}")

    # Find session files
    sessions = find_project_sessions(args.since)
    print(f"Session files to scan: {len(sessions)}")

    # Process each session
    new_records = []
    skipped = 0

    for session_file in sessions:
        result = process_session_file(session_file)
        if not result:
            continue

        for command, issue in result['commands']:
            # Check for duplicate
            key = f"{result['session_file']}:{command}:{issue}"
            if key in existing:
                skipped += 1
                if args.verbose:
                    print(f"  SKIP (exists): {command} {issue}")
                continue

            record = {
                'issue': issue,
                'command': command,
                'cost_usd': result['cost_usd'],
                'tokens': result['tokens'],
                'model': result['model'],
                'session_file': result['session_file'],
                'captured_at': datetime.now().isoformat(),
                'session_start': result['first_timestamp'],
                'session_end': result['last_timestamp'],
                'backfilled': True
            }
            new_records.append(record)
            print(f"  NEW: {command} {issue} - ${result['cost_usd']:.2f}")

    print(f"\n" + "=" * 60)
    print(f"Summary:")
    print(f"  New records found: {len(new_records)}")
    print(f"  Skipped (duplicates): {skipped}")

    if new_records:
        # Group by command
        by_command = {}
        for r in new_records:
            cmd = r['command']
            by_command[cmd] = by_command.get(cmd, 0) + 1

        print(f"\n  By command:")
        for cmd, count in sorted(by_command.items()):
            print(f"    {cmd}: {count}")

        total_cost = sum(r['cost_usd'] for r in new_records)
        print(f"\n  Total cost to add: ${total_cost:.2f}")

    if args.apply and new_records:
        print(f"\nWriting {len(new_records)} records to {COSTS_FILE}...")
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(COSTS_FILE, 'a', encoding='utf-8') as f:
            for record in new_records:
                f.write(json.dumps(record) + '\n')
        print("Done!")
    elif new_records:
        print(f"\nRun with --apply to write records to {COSTS_FILE}")

    print("=" * 60)


if __name__ == "__main__":
    main()

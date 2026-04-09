#!/usr/bin/env python3
"""
Capture cost from the current Claude Code session and store it.
Designed to be called at the end of /work and /validate commands.

Usage:
    python3 scripts/capture_session_cost.py <issue_key> <command> [--session-file <path>]

Output:
    - Appends to output/costs.jsonl for batch analysis
    - Prints JSON for agentdb memory storage
"""

import json
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime
from glob import glob

# Model pricing (per 1M tokens)
MODEL_PRICING = {
    'claude-opus-4-6': {'input': 15.0, 'output': 75.0, 'cache_read': 1.5, 'cache_write': 18.75},
    'claude-opus-4-5-20251101': {'input': 15.0, 'output': 75.0, 'cache_read': 1.5, 'cache_write': 18.75},
    'claude-3-5-sonnet-20241022': {'input': 3.0, 'output': 15.0, 'cache_read': 0.3, 'cache_write': 3.75},
    'claude-sonnet-4-20250514': {'input': 3.0, 'output': 15.0, 'cache_read': 0.3, 'cache_write': 3.75},
    'default': {'input': 3.0, 'output': 15.0, 'cache_read': 0.3, 'cache_write': 3.75},
}


def find_current_session() -> Path | None:
    """Find the most recently modified conversation file."""
    claude_projects = Path.home() / ".claude" / "projects"
    if not claude_projects.exists():
        return None

    jsonl_files = list(claude_projects.rglob("*.jsonl"))
    # Filter out agent files
    jsonl_files = [f for f in jsonl_files if not f.name.startswith('agent-')]

    if not jsonl_files:
        return None

    # Return most recently modified
    return max(jsonl_files, key=lambda f: f.stat().st_mtime)


def calculate_cost_from_usage(usage: dict, model: str = 'default') -> float:
    """Calculate cost from usage stats."""
    if not usage or not isinstance(usage, dict):
        return 0.0

    pricing = MODEL_PRICING.get(model, MODEL_PRICING['default'])

    input_tokens = usage.get('input_tokens', 0)
    output_tokens = usage.get('output_tokens', 0)
    cache_read = usage.get('cache_read_input_tokens', 0)
    cache_write = usage.get('cache_creation_input_tokens', 0)

    cost = (
        (input_tokens / 1_000_000) * pricing['input'] +
        (output_tokens / 1_000_000) * pricing['output'] +
        (cache_read / 1_000_000) * pricing['cache_read'] +
        (cache_write / 1_000_000) * pricing['cache_write']
    )

    return cost


def extract_session_cost(session_file: Path) -> dict:
    """Extract total cost and token usage from a session file."""
    total_cost = 0.0
    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_write = 0
    model_used = 'default'
    first_timestamp = None
    last_timestamp = None

    try:
        with open(session_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())

                    # Track timestamps
                    ts = entry.get('timestamp')
                    if ts:
                        if not first_timestamp:
                            first_timestamp = ts
                        last_timestamp = ts

                    # Extract costs from assistant messages
                    if entry.get('type') == 'assistant':
                        message = entry.get('message', {})
                        usage = message.get('usage', {})
                        model = message.get('model', 'default')

                        if usage:
                            model_used = model
                            total_input += usage.get('input_tokens', 0)
                            total_output += usage.get('output_tokens', 0)
                            total_cache_read += usage.get('cache_read_input_tokens', 0)
                            total_cache_write += usage.get('cache_creation_input_tokens', 0)
                            total_cost += calculate_cost_from_usage(usage, model)

                except json.JSONDecodeError:
                    continue
                except Exception:
                    continue

    except Exception as e:
        print(f"Error reading session: {e}", file=sys.stderr)
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
        'first_timestamp': first_timestamp,
        'last_timestamp': last_timestamp
    }


def append_to_jsonl(record: dict, output_file: Path):
    """Append a cost record to the JSONL file."""
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record) + '\n')


def main():
    parser = argparse.ArgumentParser(description='Capture session cost for an issue')
    parser.add_argument('issue_key', help='Jira issue key (e.g., PROJ-123)')
    parser.add_argument('command', help='Command that was run (e.g., work, validate)')
    parser.add_argument('--session-file', type=Path, help='Specific session file to analyze')
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).parent.parent / 'output',
                        help='Output directory for costs.jsonl')
    parser.add_argument('--no-append', action='store_true', help='Do not append to JSONL file')
    parser.add_argument('--json', action='store_true', help='Output as JSON for memory storage')

    args = parser.parse_args()

    # Find session file
    session_file = args.session_file or find_current_session()
    if not session_file or not session_file.exists():
        print("No session file found", file=sys.stderr)
        sys.exit(1)

    # Extract cost
    session_data = extract_session_cost(session_file)
    if not session_data:
        print("Could not extract session data", file=sys.stderr)
        sys.exit(1)

    # Build cost record
    timestamp = datetime.now().isoformat()
    cost_record = {
        'issue': args.issue_key.upper(),
        'command': args.command.lower(),
        'cost_usd': session_data['cost_usd'],
        'tokens': session_data['tokens'],
        'model': session_data['model'],
        'session_file': session_data['session_file'],
        'captured_at': timestamp,
        'session_start': session_data.get('first_timestamp'),
        'session_end': session_data.get('last_timestamp')
    }

    # Append to JSONL unless disabled
    if not args.no_append:
        output_file = args.output_dir / 'costs.jsonl'
        append_to_jsonl(cost_record, output_file)
        print(f"Cost appended to {output_file}", file=sys.stderr)

    # Output for agentdb memory storage
    if args.json:
        print(json.dumps(cost_record))
    else:
        print(f"Issue: {cost_record['issue']}")
        print(f"Command: {cost_record['command']}")
        print(f"Cost: ${cost_record['cost_usd']:.4f}")
        print(f"Tokens: {cost_record['tokens']['total']:,}")
        print(f"Model: {cost_record['model']}")


if __name__ == '__main__':
    main()

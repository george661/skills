#!/usr/bin/env python3
"""
Extract issue IDs, skill commands, and costs from Claude Code conversation history.
Dynamically discovers all available commands from .claude/commands/*.md files.
Outputs CSV format: issue_id, command, timestamp, cost_usd, session_file
"""

import json
import re
import os
import sys
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import datetime
import csv

# Default paths
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
SCRIPT_DIR = Path(__file__).parent
COMMANDS_DIR = SCRIPT_DIR.parent / ".claude" / "commands"

# Regex pattern for issue IDs (configurable prefix)
DEFAULT_ISSUE_PREFIX = "${PROJECT_KEY}"

# Model pricing (per 1M tokens)
MODEL_PRICING = {
    'claude-opus-4-6': {'input': 15.0, 'output': 75.0, 'cache_read': 1.5, 'cache_write': 18.75},
    'claude-opus-4-5-20251101': {'input': 15.0, 'output': 75.0, 'cache_read': 1.5, 'cache_write': 18.75},
    'claude-3-5-sonnet-20241022': {'input': 3.0, 'output': 15.0, 'cache_read': 0.3, 'cache_write': 3.75},
    'claude-sonnet-4-20250514': {'input': 3.0, 'output': 15.0, 'cache_read': 0.3, 'cache_write': 3.75},
    'default': {'input': 3.0, 'output': 15.0, 'cache_read': 0.3, 'cache_write': 3.75},
}


def discover_commands(commands_dir: Path) -> list[str]:
    """Discover all available commands from .claude/commands/*.md files."""
    commands = []
    if commands_dir.exists():
        for md_file in commands_dir.glob("*.md"):
            cmd_name = md_file.stem  # filename without .md
            commands.append(cmd_name)
    return sorted(commands)


def build_command_patterns(commands: list[str], issue_prefix: str) -> dict[str, re.Pattern]:
    """Build regex patterns for each command."""
    patterns = {}
    for cmd in commands:
        # Match /command ISSUE-123 or /command ISSUE-123 with optional trailing text
        pattern = re.compile(
            rf'/{re.escape(cmd)}\s+({re.escape(issue_prefix)}-\d+)',
            re.IGNORECASE
        )
        patterns[cmd] = pattern
    return patterns


def calculate_cost_from_usage(usage: dict, model: str = 'default') -> float:
    """Calculate cost from usage stats and model pricing."""
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


def extract_nested_cost(content: str) -> float:
    """Extract costUSD or total_cost_usd from nested JSON in tool results."""
    total = 0.0
    if not isinstance(content, str):
        return total

    cost_pattern = re.compile(r'"costUSD"\s*:\s*([\d.]+)')
    total_cost_pattern = re.compile(r'"total_cost_usd"\s*:\s*([\d.]+)')

    for match in cost_pattern.finditer(content):
        try:
            total += float(match.group(1))
        except ValueError:
            pass

    for match in total_cost_pattern.finditer(content):
        try:
            total += float(match.group(1))
        except ValueError:
            pass

    return total


def extract_from_jsonl(file_path: Path, command_patterns: dict[str, re.Pattern], primary: str = 'last') -> list[dict]:
    """Extract issue, command, timestamp, and cost from a single JSONL conversation file.

    Args:
        primary: 'first' or 'last' - which command to use as primary when multiple per issue
    """
    results = []
    session_data = {
        'issues': set(),
        'commands': [],  # tuples of (cmd_type, issue_id, timestamp)
        'total_cost': 0.0,
        'file': str(file_path)
    }

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())

                    # Look for commands in user messages
                    if entry.get('type') == 'user':
                        message = entry.get('message', {})
                        content = message.get('content', '')

                        # Handle different content formats
                        if isinstance(content, str):
                            text = content
                        elif isinstance(content, list):
                            text = ' '.join(
                                c.get('text', '') if isinstance(c, dict) else str(c)
                                for c in content
                            )
                        else:
                            text = str(content)

                        timestamp = entry.get('timestamp', '')

                        # Check for each command pattern
                        for cmd_name, pattern in command_patterns.items():
                            match = pattern.search(text)
                            if match:
                                issue_id = match.group(1)
                                session_data['commands'].append((cmd_name, issue_id, timestamp))
                                session_data['issues'].add(issue_id)

                    # Extract costs from assistant messages
                    if entry.get('type') == 'assistant':
                        message = entry.get('message', {})
                        usage = message.get('usage', {})
                        model = message.get('model', 'default')
                        if usage:
                            session_data['total_cost'] += calculate_cost_from_usage(usage, model)

                    # Extract costs from tool results
                    tool_result = entry.get('toolUseResult', {})
                    if tool_result:
                        stdout = tool_result.get('stdout', '')
                        if stdout:
                            session_data['total_cost'] += extract_nested_cost(stdout)

                    # Extract costs from subagent results
                    if entry.get('type') == 'user':
                        message = entry.get('message', {})
                        content = message.get('content', [])
                        if isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get('type') == 'tool_result':
                                    result_content = c.get('content', '')
                                    if isinstance(result_content, str):
                                        session_data['total_cost'] += extract_nested_cost(result_content)

                except json.JSONDecodeError:
                    continue
                except Exception:
                    continue

    except Exception as e:
        print(f"Error reading {file_path}: {e}", file=sys.stderr)
        return []

    # Group by issue_id, keeping only ONE command per issue (prevents double-counting)
    # 'primary' parameter determines whether to use first or last command
    primary_by_issue = {}  # issue_id -> (cmd_type, timestamp)
    for cmd_type, issue_id, timestamp in session_data['commands']:
        if issue_id not in primary_by_issue:
            primary_by_issue[issue_id] = (cmd_type, timestamp)
        elif primary == 'first' and timestamp < primary_by_issue[issue_id][1]:
            # Earlier timestamp = primary command
            primary_by_issue[issue_id] = (cmd_type, timestamp)
        elif primary == 'last' and timestamp > primary_by_issue[issue_id][1]:
            # Later timestamp = primary command
            primary_by_issue[issue_id] = (cmd_type, timestamp)

    if primary_by_issue and session_data['total_cost'] > 0:
        # Split cost among unique ISSUES (not commands) to prevent double-counting
        cost_per_issue = session_data['total_cost'] / len(primary_by_issue)
        for issue_id, (cmd_type, timestamp) in primary_by_issue.items():
            results.append({
                'issue_id': issue_id,
                'command': cmd_type,
                'timestamp': timestamp,
                'cost_usd': round(cost_per_issue, 6),
                'session_file': file_path.name
            })
    elif primary_by_issue:
        for issue_id, (cmd_type, timestamp) in primary_by_issue.items():
            results.append({
                'issue_id': issue_id,
                'command': cmd_type,
                'timestamp': timestamp,
                'cost_usd': 0.0,
                'session_file': file_path.name
            })

    return results


def scan_all_projects(command_patterns: dict[str, re.Pattern], projects_dir: Path, primary: str = 'last') -> list[dict]:
    """Scan all project directories for conversation files."""
    all_results = []

    if not projects_dir.exists():
        print(f"Claude projects directory not found: {projects_dir}", file=sys.stderr)
        return all_results

    jsonl_files = list(projects_dir.rglob("*.jsonl"))
    print(f"Found {len(jsonl_files)} conversation files to scan...", file=sys.stderr)

    for i, jsonl_file in enumerate(jsonl_files):
        # Skip agent files (subagent logs)
        if jsonl_file.name.startswith('agent-'):
            continue

        results = extract_from_jsonl(jsonl_file, command_patterns, primary)
        all_results.extend(results)

        if (i + 1) % 100 == 0:
            print(f"Processed {i + 1}/{len(jsonl_files)} files...", file=sys.stderr)

    return all_results


def aggregate_by_issue(results: list[dict], commands: list[str]) -> dict:
    """Aggregate costs by issue and command type."""
    aggregated = defaultdict(lambda: {cmd: 0.0 for cmd in commands} | {f'{cmd}_count': 0 for cmd in commands})

    for r in results:
        issue = r['issue_id']
        cmd = r['command']
        cost = r['cost_usd']

        if cmd in aggregated[issue]:
            aggregated[issue][cmd] += cost
            aggregated[issue][f'{cmd}_count'] += 1

    return aggregated


def aggregate_by_command(results: list[dict]) -> dict:
    """Aggregate costs by command type."""
    aggregated = defaultdict(lambda: {'cost': 0.0, 'count': 0, 'issues': set()})

    for r in results:
        cmd = r['command']
        aggregated[cmd]['cost'] += r['cost_usd']
        aggregated[cmd]['count'] += 1
        aggregated[cmd]['issues'].add(r['issue_id'])

    return aggregated


def print_summary(results: list[dict], commands: list[str], aggregated_by_issue: dict, aggregated_by_command: dict):
    """Print summary statistics to stderr."""
    print("\n" + "=" * 80, file=sys.stderr)
    print("COMMAND COST ANALYSIS REPORT", file=sys.stderr)
    print("=" * 80, file=sys.stderr)

    # Summary by command
    print("\n--- Cost by Command ---", file=sys.stderr)
    print(f"{'Command':<25} {'Total $':<12} {'Count':<8} {'Avg $':<12} {'Issues':<8}", file=sys.stderr)
    print("-" * 65, file=sys.stderr)

    total_cost = 0
    total_count = 0
    for cmd in sorted(aggregated_by_command.keys()):
        data = aggregated_by_command[cmd]
        avg_cost = data['cost'] / data['count'] if data['count'] > 0 else 0
        print(f"{cmd:<25} ${data['cost']:<11.2f} {data['count']:<8} ${avg_cost:<11.2f} {len(data['issues']):<8}", file=sys.stderr)
        total_cost += data['cost']
        total_count += data['count']

    print("-" * 65, file=sys.stderr)
    avg_total = total_cost / total_count if total_count > 0 else 0
    print(f"{'TOTAL':<25} ${total_cost:<11.2f} {total_count:<8} ${avg_total:<11.2f}", file=sys.stderr)

    # Top 10 most expensive issues
    print("\n--- Top 10 Most Expensive Issues ---", file=sys.stderr)
    issue_totals = []
    for issue, data in aggregated_by_issue.items():
        issue_cost = sum(data[cmd] for cmd in commands if cmd in data)
        issue_count = sum(data.get(f'{cmd}_count', 0) for cmd in commands)
        issue_totals.append((issue, issue_cost, issue_count))

    issue_totals.sort(key=lambda x: x[1], reverse=True)
    print(f"{'Issue':<12} {'Total $':<12} {'Sessions':<10}", file=sys.stderr)
    print("-" * 34, file=sys.stderr)
    for issue, cost, count in issue_totals[:10]:
        print(f"{issue:<12} ${cost:<11.2f} {count:<10}", file=sys.stderr)

    # Issues with high validation-to-work ratio
    print("\n--- Issues with High Validate:Work Ratio (>3x) ---", file=sys.stderr)
    high_ratio = []
    for issue, data in aggregated_by_issue.items():
        work_cost = data.get('work', 0) + data.get('implement', 0) + data.get('create-implementation-plan', 0)
        validate_cost = data.get('validate', 0)
        if work_cost > 0 and validate_cost > work_cost * 3:
            high_ratio.append((issue, work_cost, validate_cost, validate_cost / work_cost))

    high_ratio.sort(key=lambda x: x[3], reverse=True)
    if high_ratio:
        print(f"{'Issue':<12} {'Work $':<12} {'Validate $':<12} {'Ratio':<8}", file=sys.stderr)
        print("-" * 44, file=sys.stderr)
        for issue, work, validate, ratio in high_ratio[:10]:
            print(f"{issue:<12} ${work:<11.2f} ${validate:<11.2f} {ratio:<7.1f}x", file=sys.stderr)
    else:
        print("No issues found with high validate:work ratio.", file=sys.stderr)

    print("\n" + "=" * 80, file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description='Extract command costs from Claude Code conversation history'
    )
    parser.add_argument(
        '--commands-dir',
        type=Path,
        default=COMMANDS_DIR,
        help=f'Directory containing command .md files (default: {COMMANDS_DIR})'
    )
    parser.add_argument(
        '--projects-dir',
        type=Path,
        default=CLAUDE_PROJECTS_DIR,
        help=f'Claude projects directory (default: {CLAUDE_PROJECTS_DIR})'
    )
    parser.add_argument(
        '--issue-prefix',
        default=DEFAULT_ISSUE_PREFIX,
        help=f'Issue ID prefix (default: {DEFAULT_ISSUE_PREFIX})'
    )
    parser.add_argument(
        '--output',
        type=Path,
        help='Output CSV file (default: stdout)'
    )
    parser.add_argument(
        '--summary-only',
        action='store_true',
        help='Only print summary, no CSV output'
    )
    parser.add_argument(
        '--list-commands',
        action='store_true',
        help='List discovered commands and exit'
    )
    parser.add_argument(
        '--primary',
        choices=['first', 'last'],
        default='last',
        help='Which command to use as primary when multiple commands per issue in session (default: last)'
    )

    args = parser.parse_args()

    # Discover commands
    commands = discover_commands(args.commands_dir)

    if args.list_commands:
        print("Discovered commands:")
        for cmd in commands:
            print(f"  /{cmd}")
        return

    if not commands:
        print(f"No commands found in {args.commands_dir}", file=sys.stderr)
        print("Make sure .claude/commands/*.md files exist.", file=sys.stderr)
        return

    print(f"Discovered {len(commands)} commands: {', '.join(commands[:10])}{'...' if len(commands) > 10 else ''}", file=sys.stderr)

    # Build patterns
    command_patterns = build_command_patterns(commands, args.issue_prefix)

    # Scan conversations
    print("Scanning Claude Code conversation history...", file=sys.stderr)
    results = scan_all_projects(command_patterns, args.projects_dir, args.primary)

    if not results:
        print("No commands found in conversation history.", file=sys.stderr)
        return

    print(f"\nFound {len(results)} command instances.", file=sys.stderr)

    # Aggregate
    aggregated_by_issue = aggregate_by_issue(results, commands)
    aggregated_by_command = aggregate_by_command(results)

    # Print summary
    print_summary(results, commands, aggregated_by_issue, aggregated_by_command)

    # Output CSV
    if not args.summary_only:
        output_file = args.output
        if output_file:
            f = open(output_file, 'w', newline='')
        else:
            f = sys.stdout

        writer = csv.DictWriter(f, fieldnames=['issue_id', 'command', 'timestamp', 'cost_usd', 'session_file'])
        writer.writeheader()

        for r in sorted(results, key=lambda x: (x['timestamp'] or '', x['issue_id'], x['command'])):
            writer.writerow(r)

        if output_file:
            f.close()
            print(f"\nCSV output written to: {output_file}", file=sys.stderr)


if __name__ == '__main__':
    main()

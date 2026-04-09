#!/usr/bin/env python3
"""
Aggregate and query costs from the incremental costs.jsonl file.

Usage:
    python3 scripts/aggregate_costs.py                    # Summary by command
    python3 scripts/aggregate_costs.py --by-issue         # Summary by issue
    python3 scripts/aggregate_costs.py --issue PROJ-123     # Costs for specific issue
    python3 scripts/aggregate_costs.py --since 2025-01-01 # Costs since date
    python3 scripts/aggregate_costs.py --top 10           # Top 10 expensive issues
    python3 scripts/aggregate_costs.py --json             # Output as JSON
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

COSTS_FILE = Path(__file__).parent.parent / "output" / "costs.jsonl"


def load_costs(costs_file: Path, since: str = None) -> list[dict]:
    """Load cost records from JSONL file."""
    records = []

    if not costs_file.exists():
        return records

    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
        except ValueError:
            since_dt = datetime.strptime(since, "%Y-%m-%d")

    with open(costs_file, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                record = json.loads(line.strip())

                # Filter by date if specified
                if since_dt:
                    captured = record.get('captured_at', '')
                    if captured:
                        try:
                            record_dt = datetime.fromisoformat(captured.replace('Z', '+00:00'))
                            if record_dt < since_dt:
                                continue
                        except ValueError:
                            pass

                records.append(record)
            except json.JSONDecodeError:
                continue

    return records


def aggregate_by_command(records: list[dict]) -> dict:
    """Aggregate costs by command type."""
    aggregated = defaultdict(lambda: {'cost': 0.0, 'count': 0, 'issues': set()})

    for r in records:
        cmd = r.get('command', 'unknown')
        aggregated[cmd]['cost'] += r.get('cost_usd', 0)
        aggregated[cmd]['count'] += 1
        aggregated[cmd]['issues'].add(r.get('issue', ''))

    return aggregated


def aggregate_by_issue(records: list[dict]) -> dict:
    """Aggregate costs by issue."""
    aggregated = defaultdict(lambda: {'cost': 0.0, 'commands': defaultdict(float), 'count': 0})

    for r in records:
        issue = r.get('issue', 'unknown')
        cmd = r.get('command', 'unknown')
        cost = r.get('cost_usd', 0)

        aggregated[issue]['cost'] += cost
        aggregated[issue]['commands'][cmd] += cost
        aggregated[issue]['count'] += 1

    return aggregated


def print_command_summary(aggregated: dict, output_json: bool = False):
    """Print summary by command."""
    if output_json:
        result = {cmd: {'cost': data['cost'], 'count': data['count'], 'issues': len(data['issues'])}
                  for cmd, data in aggregated.items()}
        print(json.dumps(result, indent=2))
        return

    print("\n" + "=" * 60)
    print("COST SUMMARY BY COMMAND")
    print("=" * 60)
    print(f"{'Command':<20} {'Total $':<12} {'Count':<8} {'Avg $':<12} {'Issues':<8}")
    print("-" * 60)

    total_cost = 0
    total_count = 0

    for cmd in sorted(aggregated.keys()):
        data = aggregated[cmd]
        avg = data['cost'] / data['count'] if data['count'] > 0 else 0
        print(f"{cmd:<20} ${data['cost']:<11.2f} {data['count']:<8} ${avg:<11.2f} {len(data['issues']):<8}")
        total_cost += data['cost']
        total_count += data['count']

    print("-" * 60)
    avg_total = total_cost / total_count if total_count > 0 else 0
    print(f"{'TOTAL':<20} ${total_cost:<11.2f} {total_count:<8} ${avg_total:<11.2f}")
    print("=" * 60)


def print_issue_summary(aggregated: dict, top_n: int = None, output_json: bool = False):
    """Print summary by issue."""
    # Sort by total cost descending
    sorted_issues = sorted(aggregated.items(), key=lambda x: x[1]['cost'], reverse=True)

    if top_n:
        sorted_issues = sorted_issues[:top_n]

    if output_json:
        result = {issue: {'cost': data['cost'], 'count': data['count'],
                         'commands': dict(data['commands'])}
                  for issue, data in sorted_issues}
        print(json.dumps(result, indent=2))
        return

    print("\n" + "=" * 70)
    print(f"COST SUMMARY BY ISSUE{' (Top ' + str(top_n) + ')' if top_n else ''}")
    print("=" * 70)
    print(f"{'Issue':<12} {'Total $':<12} {'Sessions':<10} {'Work $':<12} {'Validate $':<12}")
    print("-" * 70)

    for issue, data in sorted_issues:
        work_cost = data['commands'].get('work', 0)
        validate_cost = data['commands'].get('validate', 0)
        print(f"{issue:<12} ${data['cost']:<11.2f} {data['count']:<10} ${work_cost:<11.2f} ${validate_cost:<11.2f}")

    print("=" * 70)


def print_issue_detail(records: list[dict], issue: str, output_json: bool = False):
    """Print detailed costs for a specific issue."""
    issue_records = [r for r in records if r.get('issue', '').upper() == issue.upper()]

    if not issue_records:
        print(f"No cost records found for {issue}")
        return

    if output_json:
        print(json.dumps(issue_records, indent=2))
        return

    print(f"\n{'=' * 70}")
    print(f"COST DETAIL: {issue}")
    print("=" * 70)

    total = sum(r.get('cost_usd', 0) for r in issue_records)
    total_tokens = sum(r.get('tokens', {}).get('total', 0) for r in issue_records)

    print(f"Total Cost: ${total:.2f}")
    print(f"Total Tokens: {total_tokens:,}")
    print(f"Sessions: {len(issue_records)}")
    print()
    print(f"{'Timestamp':<25} {'Command':<12} {'Cost':<10} {'Tokens':<12} {'Model':<20}")
    print("-" * 70)

    for r in sorted(issue_records, key=lambda x: x.get('captured_at', '')):
        ts = r.get('captured_at', '')[:19] if r.get('captured_at') else 'N/A'
        cmd = r.get('command', 'unknown')
        cost = r.get('cost_usd', 0)
        tokens = r.get('tokens', {}).get('total', 0)
        model = r.get('model', 'unknown')[:20]
        print(f"{ts:<25} {cmd:<12} ${cost:<9.2f} {tokens:<12,} {model:<20}")

    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description='Aggregate and query costs')
    parser.add_argument('--costs-file', type=Path, default=COSTS_FILE,
                        help=f'Path to costs.jsonl (default: {COSTS_FILE})')
    parser.add_argument('--by-issue', action='store_true',
                        help='Show summary by issue instead of by command')
    parser.add_argument('--issue', type=str,
                        help='Show detailed costs for a specific issue')
    parser.add_argument('--since', type=str,
                        help='Only include costs since date (YYYY-MM-DD)')
    parser.add_argument('--top', type=int,
                        help='Show only top N expensive issues')
    parser.add_argument('--json', action='store_true',
                        help='Output as JSON')

    args = parser.parse_args()

    # Load records
    records = load_costs(args.costs_file, args.since)

    if not records:
        print(f"No cost records found in {args.costs_file}", file=sys.stderr)
        print("Costs are captured when /work and /validate commands complete.", file=sys.stderr)
        return

    print(f"Loaded {len(records)} cost records", file=sys.stderr)

    # Output based on args
    if args.issue:
        print_issue_detail(records, args.issue, args.json)
    elif args.by_issue or args.top:
        aggregated = aggregate_by_issue(records)
        print_issue_summary(aggregated, args.top, args.json)
    else:
        aggregated = aggregate_by_command(records)
        print_command_summary(aggregated, args.json)


if __name__ == '__main__':
    main()

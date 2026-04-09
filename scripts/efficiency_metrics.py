#!/usr/bin/env python3
"""
Efficiency Metrics Tracker

Compares session metrics before and after tool efficiency improvements.
Tracks: token usage, tool result sizes, compression savings, checkpoint usage.

Usage:
  python3 scripts/efficiency_metrics.py baseline    # Analyze pre-change logs
  python3 scripts/efficiency_metrics.py current     # Analyze post-change logs
  python3 scripts/efficiency_metrics.py compare     # Compare before/after
  python3 scripts/efficiency_metrics.py report      # Generate full report
"""

import json
import os
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Any, Optional
import argparse

# Configuration
OUTPUT_DIR = Path(__file__).parent.parent / "output"
METRICS_DIR = Path(__file__).parent.parent / "metrics"
COMPRESSION_LOG = Path.home() / ".claude" / "result-compression.log"
CHECKPOINT_DIR = Path("/tmp/checkpoints")

# Efficiency changes deployed on this date
CHANGE_DATE = datetime(2026, 1, 8)

# Model pricing (per 1M tokens)
MODEL_PRICING = {
    'claude-opus-4-6': {'input': 15.0, 'output': 75.0, 'cache_read': 1.5, 'cache_write': 18.75},
    'claude-opus-4-5-20251101': {'input': 15.0, 'output': 75.0, 'cache_read': 1.5, 'cache_write': 18.75},
    'claude-sonnet-4-20250514': {'input': 3.0, 'output': 15.0, 'cache_read': 0.3, 'cache_write': 3.75},
    'default': {'input': 3.0, 'output': 15.0, 'cache_read': 0.3, 'cache_write': 3.75},
}

# REST skills and MCP tools to track
# Note: Jira and Bitbucket now use REST skills (npx tsx .claude/skills/*/...)
# These are tracked by name for log analysis
TRACKED_TOOLS = [
    # Jira REST skills
    'jira-mcp/search_issues',
    'jira-mcp/get_issue',
    'jira-mcp/list_transitions',
    'jira-mcp/transition_issue',
    # Bitbucket REST skills
    'bitbucket-mcp/list_pull_requests',
    'bitbucket-mcp/list_pipelines',
    'bitbucket-mcp/get_pipeline_step_log',
    'bitbucket-mcp/create_pull_request',
    # MCP tools (still active)
    'mcp__agentdb__reflexion_store_episode',
    'mcp__agentdb__reflexion_retrieve_relevant',
]

# All tracked commands (must match hooks/cost-capture.py)
TRACKED_COMMANDS = [
    # Core workflow commands
    "work", "validate", "implement", "create-implementation-plan",
    "review", "fix-pr", "resolve-pr",
    # Epic lifecycle commands
    "plan", "groom", "validate-plan", "fix-plan", "validate-groom",
    # Legacy aliases (for backward compatibility with historical data)
    "validate-prp", "fix-prp",
    # Creation commands
    "next", "issue", "bug", "change",
    # Analysis commands
    "audit", "investigate", "garden", "garden-accuracy",
    "garden-cache", "garden-readiness", "garden-relevancy",
    "sequence", "sequence-json",
    # Utility commands
    "consolidate-prs", "update-docs", "reclaim", "fix-pipeline",
    # Loop commands
    "loop-issue", "loop-epic", "loop-backlog",
    "loop:issue", "loop:epic", "loop:backlog",
    # Metrics commands
    "metrics:baseline", "metrics:current", "metrics:compare",
    "metrics:report", "metrics:before-after",
]

COSTS_FILE = OUTPUT_DIR / "costs.jsonl"


def parse_log_timestamp(filename: str) -> Optional[datetime]:
    """Extract timestamp from log filename."""
    # Format: PROJ-123_command_YYYYMMDD_HHMMSS.json
    match = re.search(r'_(\d{8})_(\d{6})\.json$', filename)
    if match:
        date_str = match.group(1)
        time_str = match.group(2)
        return datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H%M%S")
    return None


def calculate_cost(usage: Dict, model: str = 'default') -> float:
    """Calculate cost from token usage."""
    if not usage:
        return 0.0

    pricing = MODEL_PRICING.get(model, MODEL_PRICING['default'])

    input_tokens = usage.get('input_tokens', 0)
    output_tokens = usage.get('output_tokens', 0)
    cache_read = usage.get('cache_read_input_tokens', 0)
    cache_write = usage.get('cache_creation_input_tokens', 0)

    return (
        (input_tokens / 1_000_000) * pricing['input'] +
        (output_tokens / 1_000_000) * pricing['output'] +
        (cache_read / 1_000_000) * pricing['cache_read'] +
        (cache_write / 1_000_000) * pricing['cache_write']
    )


def analyze_session(log_file: Path) -> Dict[str, Any]:
    """Analyze a single session log file."""
    metrics = {
        'file': str(log_file.name),
        'timestamp': None,
        'total_tokens': 0,
        'input_tokens': 0,
        'output_tokens': 0,
        'cache_read_tokens': 0,
        'cache_write_tokens': 0,
        'cost_usd': 0.0,
        'tool_calls': 0,
        'mcp_tool_calls': 0,
        'tool_result_chars': 0,
        'tracked_tool_calls': defaultdict(int),
        'errors': 0,
        'model': 'unknown',
    }

    metrics['timestamp'] = parse_log_timestamp(log_file.name)

    try:
        with open(log_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Extract model
                if entry.get('type') == 'assistant':
                    msg = entry.get('message', {})
                    if 'model' in msg:
                        metrics['model'] = msg['model']

                    # Extract token usage
                    usage = msg.get('usage', {})
                    if usage:
                        metrics['input_tokens'] += usage.get('input_tokens', 0)
                        metrics['output_tokens'] += usage.get('output_tokens', 0)
                        metrics['cache_read_tokens'] += usage.get('cache_read_input_tokens', 0)
                        metrics['cache_write_tokens'] += usage.get('cache_creation_input_tokens', 0)

                    # Count tool calls
                    content = msg.get('content', [])
                    for item in content:
                        if item.get('type') == 'tool_use':
                            metrics['tool_calls'] += 1
                            tool_name = item.get('name', '')

                            if tool_name.startswith('mcp__'):
                                metrics['mcp_tool_calls'] += 1

                            if tool_name in TRACKED_TOOLS:
                                metrics['tracked_tool_calls'][tool_name] += 1

                # Count tool results
                if entry.get('type') == 'tool_result':
                    result = entry.get('content', '')
                    if isinstance(result, str):
                        metrics['tool_result_chars'] += len(result)
                    elif isinstance(result, dict):
                        metrics['tool_result_chars'] += len(json.dumps(result))

                # Count errors
                if entry.get('type') == 'error':
                    metrics['errors'] += 1

    except Exception as e:
        metrics['parse_error'] = str(e)

    # Calculate totals
    metrics['total_tokens'] = (
        metrics['input_tokens'] +
        metrics['output_tokens'] +
        metrics['cache_read_tokens'] +
        metrics['cache_write_tokens']
    )
    metrics['cost_usd'] = calculate_cost({
        'input_tokens': metrics['input_tokens'],
        'output_tokens': metrics['output_tokens'],
        'cache_read_input_tokens': metrics['cache_read_tokens'],
        'cache_creation_input_tokens': metrics['cache_write_tokens'],
    }, metrics['model'])

    return metrics


def analyze_compression_log() -> Dict[str, Any]:
    """Analyze result compression log for savings metrics."""
    if not COMPRESSION_LOG.exists():
        return {'exists': False, 'entries': 0}

    metrics = {
        'exists': True,
        'entries': 0,
        'total_original_kb': 0,
        'total_compressed_kb': 0,
        'savings_pct': 0,
        'by_tool': defaultdict(lambda: {'count': 0, 'savings_pct': []}),
    }

    try:
        with open(COMPRESSION_LOG, 'r') as f:
            for line in f:
                metrics['entries'] += 1
                # Parse: 2025-01-08T11:30:00 - Compressed tool: 45K chars -> 8K chars (82.2% reduction)
                match = re.search(r'Compressed (\S+): (\d+)K chars -> (\d+)K chars \((\d+\.?\d*)% reduction\)', line)
                if match:
                    tool = match.group(1)
                    original = int(match.group(2))
                    compressed = int(match.group(3))
                    pct = float(match.group(4))

                    metrics['total_original_kb'] += original
                    metrics['total_compressed_kb'] += compressed
                    metrics['by_tool'][tool]['count'] += 1
                    metrics['by_tool'][tool]['savings_pct'].append(pct)

        if metrics['total_original_kb'] > 0:
            metrics['savings_pct'] = (
                (metrics['total_original_kb'] - metrics['total_compressed_kb']) /
                metrics['total_original_kb'] * 100
            )

    except Exception as e:
        metrics['error'] = str(e)

    return metrics


def analyze_costs_by_command() -> Dict[str, Any]:
    """Analyze costs.jsonl for per-command cost breakdown."""
    if not COSTS_FILE.exists():
        return {'exists': False, 'entries': 0}

    metrics = {
        'exists': True,
        'entries': 0,
        'total_cost_usd': 0.0,
        'by_command': defaultdict(lambda: {
            'count': 0,
            'total_cost': 0.0,
            'total_tokens': 0,
            'avg_cost': 0.0,
            'issues': set()
        }),
        'by_issue': defaultdict(lambda: {
            'commands': [],
            'total_cost': 0.0,
            'total_tokens': 0
        }),
    }

    try:
        with open(COSTS_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                    metrics['entries'] += 1

                    command = entry.get('command', 'unknown')
                    issue = entry.get('issue', 'UNKNOWN')
                    cost = entry.get('cost_usd', 0.0)
                    tokens = entry.get('tokens', {})
                    total_tokens = tokens.get('total', 0) if isinstance(tokens, dict) else 0

                    metrics['total_cost_usd'] += cost

                    # By command
                    cmd_data = metrics['by_command'][command]
                    cmd_data['count'] += 1
                    cmd_data['total_cost'] += cost
                    cmd_data['total_tokens'] += total_tokens
                    cmd_data['issues'].add(issue)

                    # By issue
                    issue_data = metrics['by_issue'][issue]
                    issue_data['commands'].append(command)
                    issue_data['total_cost'] += cost
                    issue_data['total_tokens'] += total_tokens

                except json.JSONDecodeError:
                    continue

        # Calculate averages and convert sets to lists
        for cmd, data in metrics['by_command'].items():
            if data['count'] > 0:
                data['avg_cost'] = data['total_cost'] / data['count']
            data['issues'] = list(data['issues'])

    except Exception as e:
        metrics['error'] = str(e)

    return metrics


def analyze_workflow_patterns() -> Dict[str, Any]:
    """Analyze workflow pattern training data."""
    pattern_dir = Path.home() / ".claude" / "pattern-training"
    pending_file = pattern_dir / "pending-patterns.jsonl"
    trained_file = pattern_dir / "trained-patterns.jsonl"
    log_file = pattern_dir / "workflow-patterns.jsonl"

    metrics = {
        'exists': pattern_dir.exists(),
        'pending': 0,
        'trained': 0,
        'logged': 0,
        'by_workflow_type': defaultdict(lambda: {'count': 0, 'success': 0, 'failure': 0, 'partial': 0}),
    }

    if not pattern_dir.exists():
        return metrics

    # Count pending
    if pending_file.exists():
        with open(pending_file, 'r') as f:
            metrics['pending'] = sum(1 for line in f if line.strip())

    # Count trained
    if trained_file.exists():
        with open(trained_file, 'r') as f:
            metrics['trained'] = sum(1 for line in f if line.strip())

    # Analyze log for workflow type breakdown
    if log_file.exists():
        try:
            with open(log_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        metrics['logged'] += 1

                        if entry.get('event') == 'workflow_complete':
                            wf_type = entry.get('type', 'unknown')
                            outcome = entry.get('outcome', 'partial')
                            metrics['by_workflow_type'][wf_type]['count'] += 1
                            if outcome in ['success', 'failure', 'partial']:
                                metrics['by_workflow_type'][wf_type][outcome] += 1
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass

    return metrics


def analyze_checkpoints() -> Dict[str, Any]:
    """Analyze checkpoint usage."""
    if not CHECKPOINT_DIR.exists():
        return {'exists': False, 'count': 0}

    metrics = {
        'exists': True,
        'count': 0,
        'issues': set(),
        'phases': defaultdict(int),
        'total_size_kb': 0,
    }

    try:
        for cp_file in CHECKPOINT_DIR.glob('*.json'):
            metrics['count'] += 1
            metrics['total_size_kb'] += cp_file.stat().st_size / 1024

            try:
                with open(cp_file) as f:
                    cp = json.load(f)
                    metrics['issues'].add(cp.get('issue', 'unknown'))
                    metrics['phases'][cp.get('phase', 'unknown')] += 1
            except:
                pass

        metrics['issues'] = list(metrics['issues'])

    except Exception as e:
        metrics['error'] = str(e)

    return metrics


def get_baseline_metrics() -> Dict[str, Any]:
    """Analyze logs from before the efficiency changes."""
    baseline = {
        'period': 'baseline',
        'date_range': f'before {CHANGE_DATE.strftime("%Y-%m-%d")}',
        'sessions': 0,
        'total_tokens': 0,
        'total_cost_usd': 0.0,
        'avg_tokens_per_session': 0,
        'avg_cost_per_session': 0.0,
        'avg_tool_result_chars': 0,
        'tool_calls': 0,
        'mcp_tool_calls': 0,
        'sessions_data': [],
    }

    for log_file in OUTPUT_DIR.glob('*.json'):
        ts = parse_log_timestamp(log_file.name)
        if ts and ts < CHANGE_DATE:
            session = analyze_session(log_file)
            baseline['sessions'] += 1
            baseline['total_tokens'] += session['total_tokens']
            baseline['total_cost_usd'] += session['cost_usd']
            baseline['tool_calls'] += session['tool_calls']
            baseline['mcp_tool_calls'] += session['mcp_tool_calls']
            baseline['avg_tool_result_chars'] += session['tool_result_chars']
            baseline['sessions_data'].append(session)

    if baseline['sessions'] > 0:
        baseline['avg_tokens_per_session'] = baseline['total_tokens'] / baseline['sessions']
        baseline['avg_cost_per_session'] = baseline['total_cost_usd'] / baseline['sessions']
        baseline['avg_tool_result_chars'] = baseline['avg_tool_result_chars'] / baseline['sessions']

    return baseline


def get_current_metrics() -> Dict[str, Any]:
    """Analyze logs from after the efficiency changes."""
    current = {
        'period': 'current',
        'date_range': f'after {CHANGE_DATE.strftime("%Y-%m-%d")}',
        'sessions': 0,
        'total_tokens': 0,
        'total_cost_usd': 0.0,
        'avg_tokens_per_session': 0,
        'avg_cost_per_session': 0.0,
        'avg_tool_result_chars': 0,
        'tool_calls': 0,
        'mcp_tool_calls': 0,
        'sessions_data': [],
        'compression': analyze_compression_log(),
        'checkpoints': analyze_checkpoints(),
        'costs_by_command': analyze_costs_by_command(),
        'workflow_patterns': analyze_workflow_patterns(),
    }

    for log_file in OUTPUT_DIR.glob('*.json'):
        ts = parse_log_timestamp(log_file.name)
        if ts and ts >= CHANGE_DATE:
            session = analyze_session(log_file)
            current['sessions'] += 1
            current['total_tokens'] += session['total_tokens']
            current['total_cost_usd'] += session['cost_usd']
            current['tool_calls'] += session['tool_calls']
            current['mcp_tool_calls'] += session['mcp_tool_calls']
            current['avg_tool_result_chars'] += session['tool_result_chars']
            current['sessions_data'].append(session)

    if current['sessions'] > 0:
        current['avg_tokens_per_session'] = current['total_tokens'] / current['sessions']
        current['avg_cost_per_session'] = current['total_cost_usd'] / current['sessions']
        current['avg_tool_result_chars'] = current['avg_tool_result_chars'] / current['sessions']

    return current


def compare_metrics(baseline: Dict, current: Dict) -> Dict[str, Any]:
    """Compare baseline vs current metrics."""
    comparison = {
        'baseline_sessions': baseline['sessions'],
        'current_sessions': current['sessions'],
        'metrics': {}
    }

    metrics_to_compare = [
        ('avg_tokens_per_session', 'Avg Tokens/Session', 'lower_is_better'),
        ('avg_cost_per_session', 'Avg Cost/Session ($)', 'lower_is_better'),
        ('avg_tool_result_chars', 'Avg Tool Result Size (chars)', 'lower_is_better'),
    ]

    for key, label, direction in metrics_to_compare:
        baseline_val = baseline.get(key, 0)
        current_val = current.get(key, 0)

        if baseline_val > 0:
            change_pct = ((current_val - baseline_val) / baseline_val) * 100
        else:
            change_pct = 0

        improved = (direction == 'lower_is_better' and change_pct < 0) or \
                   (direction == 'higher_is_better' and change_pct > 0)

        comparison['metrics'][key] = {
            'label': label,
            'baseline': baseline_val,
            'current': current_val,
            'change_pct': change_pct,
            'improved': improved,
        }

    return comparison


def generate_report() -> str:
    """Generate a full efficiency report."""
    baseline = get_baseline_metrics()
    current = get_current_metrics()
    comparison = compare_metrics(baseline, current)

    report = []
    report.append("=" * 60)
    report.append("TOOL EFFICIENCY METRICS REPORT")
    report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("=" * 60)

    report.append("\n## Baseline Period (Before Changes)")
    report.append(f"Date Range: {baseline['date_range']}")
    report.append(f"Sessions Analyzed: {baseline['sessions']}")
    report.append(f"Total Tokens: {baseline['total_tokens']:,}")
    report.append(f"Total Cost: ${baseline['total_cost_usd']:.2f}")
    report.append(f"Avg Tokens/Session: {baseline['avg_tokens_per_session']:,.0f}")
    report.append(f"Avg Cost/Session: ${baseline['avg_cost_per_session']:.4f}")

    report.append("\n## Current Period (After Changes)")
    report.append(f"Date Range: {current['date_range']}")
    report.append(f"Sessions Analyzed: {current['sessions']}")
    report.append(f"Total Tokens: {current['total_tokens']:,}")
    report.append(f"Total Cost: ${current['total_cost_usd']:.2f}")
    report.append(f"Avg Tokens/Session: {current['avg_tokens_per_session']:,.0f}")
    report.append(f"Avg Cost/Session: ${current['avg_cost_per_session']:.4f}")

    report.append("\n## Comparison")
    for key, data in comparison['metrics'].items():
        symbol = "✅" if data['improved'] else "❌" if data['change_pct'] > 5 else "➖"
        report.append(f"{symbol} {data['label']}: {data['change_pct']:+.1f}%")
        report.append(f"   Baseline: {data['baseline']:,.2f} → Current: {data['current']:,.2f}")

    report.append("\n## Result Compression")
    comp = current.get('compression', {})
    if comp.get('exists'):
        report.append(f"Compression Events: {comp.get('entries', 0)}")
        report.append(f"Total Original Size: {comp.get('total_original_kb', 0)}KB")
        report.append(f"Total Compressed Size: {comp.get('total_compressed_kb', 0)}KB")
        report.append(f"Overall Savings: {comp.get('savings_pct', 0):.1f}%")
    else:
        report.append("No compression log found (feature may not be active yet)")

    report.append("\n## Checkpoint Usage")
    cp = current.get('checkpoints', {})
    if cp.get('exists') and cp.get('count', 0) > 0:
        report.append(f"Total Checkpoints: {cp.get('count', 0)}")
        report.append(f"Unique Issues: {len(cp.get('issues', []))}")
        report.append(f"Total Size: {cp.get('total_size_kb', 0):.1f}KB")
    else:
        report.append("No checkpoints found (feature may not be active yet)")

    report.append("\n## Costs by Command")
    costs = current.get('costs_by_command', {})
    if costs.get('exists') and costs.get('entries', 0) > 0:
        report.append(f"Total Cost Records: {costs.get('entries', 0)}")
        report.append(f"Total Cost: ${costs.get('total_cost_usd', 0):.2f}")
        report.append("\nCommand Breakdown:")
        by_cmd = costs.get('by_command', {})
        # Sort by total cost descending
        sorted_cmds = sorted(by_cmd.items(), key=lambda x: x[1].get('total_cost', 0), reverse=True)
        for cmd, data in sorted_cmds[:15]:  # Top 15 commands
            count = data.get('count', 0)
            total = data.get('total_cost', 0)
            avg = data.get('avg_cost', 0)
            report.append(f"  /{cmd}: {count} runs, ${total:.2f} total, ${avg:.2f} avg")
    else:
        report.append("No cost data found (run /work or other commands first)")

    report.append("\n## Workflow Pattern Training")
    patterns = current.get('workflow_patterns', {})
    if patterns.get('exists'):
        report.append(f"Pending Patterns: {patterns.get('pending', 0)}")
        report.append(f"Trained Patterns: {patterns.get('trained', 0)}")
        report.append(f"Total Logged: {patterns.get('logged', 0)}")
        by_type = patterns.get('by_workflow_type', {})
        if by_type:
            report.append("\nWorkflow Type Outcomes:")
            for wf_type, data in sorted(by_type.items()):
                count = data.get('count', 0)
                success = data.get('success', 0)
                failure = data.get('failure', 0)
                partial = data.get('partial', 0)
                if count > 0:
                    success_rate = (success / count) * 100
                    report.append(f"  {wf_type}: {count} runs, {success_rate:.0f}% success ({success}✓ {failure}✗ {partial}~)")
    else:
        report.append("No pattern training data found")

    report.append("\n## Tracked Commands Coverage")
    report.append(f"Total Tracked Commands: {len(TRACKED_COMMANDS)}")
    instrumented = set(costs.get('by_command', {}).keys()) if costs.get('exists') else set()
    missing = set(TRACKED_COMMANDS) - instrumented
    if instrumented:
        report.append(f"Commands with Data: {len(instrumented)}")
    if missing:
        report.append(f"Commands without Data: {len(missing)}")
        if len(missing) <= 10:
            report.append(f"  Missing: {', '.join(sorted(missing))}")

    report.append("\n" + "=" * 60)

    return "\n".join(report)


def main():
    parser = argparse.ArgumentParser(description='Track tool efficiency metrics')
    parser.add_argument('command', choices=['baseline', 'current', 'compare', 'report'],
                        help='Action to perform')
    parser.add_argument('--json', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    if args.command == 'baseline':
        result = get_baseline_metrics()
        del result['sessions_data']  # Too verbose for output
    elif args.command == 'current':
        result = get_current_metrics()
        del result['sessions_data']
    elif args.command == 'compare':
        baseline = get_baseline_metrics()
        current = get_current_metrics()
        result = compare_metrics(baseline, current)
    elif args.command == 'report':
        if args.json:
            baseline = get_baseline_metrics()
            current = get_current_metrics()
            del baseline['sessions_data']
            del current['sessions_data']
            result = {
                'baseline': baseline,
                'current': current,
                'comparison': compare_metrics(baseline, current),
            }
        else:
            print(generate_report())
            return

    if args.json or args.command != 'report':
        print(json.dumps(result, indent=2, default=str))


if __name__ == '__main__':
    main()

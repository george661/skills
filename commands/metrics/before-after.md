<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Compare costs before and after a change date to measure efficiency improvements
arguments:
  - name: change_date
    description: Date when changes were made (YYYY-MM-DD format, defaults to today)
    required: false
---

# Cost Comparison: Before vs After Changes

Compare session costs before and after a change date to measure the impact of command/workflow modifications.

**Change Date**: $ARGUMENTS.change_date (or today if not specified)

---

## Instructions

Run the cost comparison analysis using the Python script below. This will:
1. Split costs into "before" and "after" periods based on the change date
2. Calculate average costs per command type
3. Show percentage improvement/regression
4. Identify top expensive issues in each period

```bash
python3 -c "
import json
from pathlib import Path
from datetime import datetime, date
from collections import defaultdict

# Configuration - handle both local and Docker paths
def get_costs_file():
    candidates = [
        Path('/workspace/output/costs.jsonl'),
        Path('output/costs.jsonl'),
        Path.cwd() / 'output/costs.jsonl'
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[1]  # default to relative path

COSTS_FILE = get_costs_file()
CHANGE_DATE = '$ARGUMENTS.change_date' or '$(date +%Y-%m-%d)'

# Parse change date
if CHANGE_DATE and CHANGE_DATE != '\$ARGUMENTS.change_date':
    change_dt = datetime.strptime(CHANGE_DATE, '%Y-%m-%d')
else:
    change_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

print(f'═' * 70)
print(f'COST COMPARISON REPORT')
print(f'Change Date: {change_dt.strftime(\"%Y-%m-%d\")}')
print(f'═' * 70)

# All tracked commands
TRACKED_COMMANDS = [
    'work', 'validate', 'implement', 'create-implementation-plan',
    'review', 'fix-pr', 'resolve-pr', 'plan', 'groom', 'validate-plan',
    'validate-groom', 'next', 'issue', 'bug', 'change', 'audit',
    'investigate', 'garden', 'garden-accuracy', 'garden-cache',
    'garden-readiness', 'garden-relevancy', 'sequence', 'sequence-json',
    'consolidate-prs', 'update-docs', 'reclaim', 'fix-pipeline',
    'loop:issue', 'loop:epic', 'loop:backlog',
    'metrics:baseline', 'metrics:current', 'metrics:compare',
    'metrics:report', 'metrics:before-after'
]

# Load costs
before = {cmd: [] for cmd in TRACKED_COMMANDS}
before['other'] = []
after = {cmd: [] for cmd in TRACKED_COMMANDS}
after['other'] = []

if not COSTS_FILE.exists():
    print('No costs.jsonl found. Run /work or /validate commands to generate data.')
    exit(0)

with open(COSTS_FILE, 'r') as f:
    for line in f:
        try:
            record = json.loads(line.strip())
            captured = record.get('captured_at', '')
            if not captured:
                continue

            try:
                record_dt = datetime.fromisoformat(captured.replace('Z', '+00:00'))
            except:
                record_dt = datetime.strptime(captured[:19], '%Y-%m-%dT%H:%M:%S')

            cmd = record.get('command', 'other')
            if cmd not in TRACKED_COMMANDS:
                cmd = 'other'

            cost = record.get('cost_usd', 0)
            tokens = record.get('tokens', {}).get('total', 0)
            issue = record.get('issue', 'UNKNOWN')

            entry = {'cost': cost, 'tokens': tokens, 'issue': issue, 'date': record_dt}

            if record_dt < change_dt:
                before[cmd].append(entry)
            else:
                after[cmd].append(entry)
        except:
            continue

def calc_stats(entries):
    if not entries:
        return {'count': 0, 'total': 0, 'avg': 0, 'min': 0, 'max': 0}
    costs = [e['cost'] for e in entries]
    return {
        'count': len(costs),
        'total': sum(costs),
        'avg': sum(costs) / len(costs),
        'min': min(costs),
        'max': max(costs)
    }

# Calculate stats
print()
print('BEFORE CHANGES')
print('-' * 70)
print(f'{\"Command\":<12} {\"Count\":<8} {\"Total $\":<12} {\"Avg $\":<10} {\"Min $\":<10} {\"Max $\":<10}')
print('-' * 70)

before_total = 0
before_count = 0
all_cmds = TRACKED_COMMANDS + ['other']
for cmd in all_cmds:
    stats = calc_stats(before[cmd])
    if stats['count'] > 0:
        disp_cmd = cmd[:16]  # Truncate long command names
        print(f'{disp_cmd:<16} {stats[\"count\"]:<6} \${stats[\"total\"]:<10.2f} \${stats[\"avg\"]:<8.2f} \${stats[\"min\"]:<8.2f} \${stats[\"max\"]:<8.2f}')
        before_total += stats['total']
        before_count += stats['count']

before_avg = before_total / before_count if before_count > 0 else 0
print('-' * 70)
print(f'{\"TOTAL\":<12} {before_count:<8} \${before_total:<11.2f} \${before_avg:<9.2f}')

print()
print('AFTER CHANGES')
print('-' * 70)
print(f'{\"Command\":<12} {\"Count\":<8} {\"Total $\":<12} {\"Avg $\":<10} {\"Min $\":<10} {\"Max $\":<10}')
print('-' * 70)

after_total = 0
after_count = 0
for cmd in all_cmds:
    stats = calc_stats(after[cmd])
    if stats['count'] > 0:
        disp_cmd = cmd[:16]  # Truncate long command names
        print(f'{disp_cmd:<16} {stats[\"count\"]:<6} \${stats[\"total\"]:<10.2f} \${stats[\"avg\"]:<8.2f} \${stats[\"min\"]:<8.2f} \${stats[\"max\"]:<8.2f}')
        after_total += stats['total']
        after_count += stats['count']

after_avg = after_total / after_count if after_count > 0 else 0
print('-' * 70)
print(f'{\"TOTAL\":<12} {after_count:<8} \${after_total:<11.2f} \${after_avg:<9.2f}')

# Comparison
print()
print('═' * 70)
print('COMPARISON')
print('═' * 70)

if before_count > 0 and after_count > 0:
    avg_change = ((after_avg - before_avg) / before_avg) * 100

    # Show comparison for all commands that have data in either period
    compared_cmds = []
    for cmd in all_cmds:
        b_stats = calc_stats(before[cmd])
        a_stats = calc_stats(after[cmd])

        if b_stats['count'] > 0 or a_stats['count'] > 0:
            compared_cmds.append(cmd)
            if b_stats['count'] > 0 and a_stats['count'] > 0:
                pct = ((a_stats['avg'] - b_stats['avg']) / b_stats['avg']) * 100
                emoji = '✅' if pct < 0 else '⚠️' if pct > 10 else '➖'
                disp_cmd = cmd[:16]
                print(f'{emoji} {disp_cmd}: \${b_stats[\"avg\"]:.2f} → \${a_stats[\"avg\"]:.2f} ({pct:+.1f}%)')
            elif a_stats['count'] > 0:
                disp_cmd = cmd[:16]
                print(f'🆕 {disp_cmd}: No baseline, current avg \${a_stats[\"avg\"]:.2f}')
            elif b_stats['count'] > 0:
                disp_cmd = cmd[:16]
                print(f'📉 {disp_cmd}: Baseline avg \${b_stats[\"avg\"]:.2f}, no current data')

    emoji = '✅' if avg_change < 0 else '⚠️' if avg_change > 10 else '➖'
    print()
    print(f'{emoji} Overall Average: \${before_avg:.2f} → \${after_avg:.2f} ({avg_change:+.1f}%)')
    print(f'   Commands tracked: {len(compared_cmds)}')
elif after_count > 0:
    print('No baseline data (before change date). Run more commands to compare.')
    print(f'Current average: \${after_avg:.2f} per session')
else:
    print('No data after change date yet. Run /work or /validate to generate.')

print()

# Skill Tracking Stats
skill_file = Path.home() / '.claude' / 'skill-tracking' / 'executions.jsonl'
if skill_file.exists():
    print()
    print('SKILL EXECUTIONS')
    print('-' * 70)
    skill_stats = {}
    skill_count = 0
    with open(skill_file, 'r') as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                if entry.get('phase') == 'post':
                    skill = entry.get('skill', 'unknown')
                    outcome = entry.get('outcome', 'unknown')
                    if skill not in skill_stats:
                        skill_stats[skill] = {'total': 0, 'success': 0, 'failure': 0}
                    skill_stats[skill]['total'] += 1
                    if outcome == 'success':
                        skill_stats[skill]['success'] += 1
                    elif outcome == 'failure':
                        skill_stats[skill]['failure'] += 1
                    skill_count += 1
            except:
                continue

    if skill_stats:
        print(f'{\"Skill\":<30} {\"Count\":<8} {\"Success\":<10} {\"Fail\":<8}')
        print('-' * 70)
        for skill, stats in sorted(skill_stats.items(), key=lambda x: -x[1]['total']):
            print(f'{skill[:30]:<30} {stats[\"total\"]:<8} {stats[\"success\"]:<10} {stats[\"failure\"]:<8}')
        print('-' * 70)
        print(f'Total skill executions: {skill_count}')
    else:
        print('No skill executions tracked yet.')

print()
print('═' * 70)
"
```

## Quick Reference

| Command | Description |
|---------|-------------|
| `/metrics:before-after` | Compare using today as change date |
| `/metrics:before-after 2026-01-08` | Compare using specific date |
| `/metrics:report` | Full efficiency report |
| `/metrics:current` | Current period metrics only |

## Interpreting Results

| Symbol | Meaning |
|--------|---------|
| ✅ | Improvement (cost decreased) |
| ⚠️ | Regression (cost increased >10%) |
| ➖ | No significant change |
| 🆕 | New data, no baseline to compare |

## Tips

1. **Set a baseline before changes**: Note the date before modifying commands
2. **Run enough sessions**: Need 5+ sessions in each period for meaningful comparison
3. **Compare same issue types**: `/work` on simple bugs vs complex features will vary
4. **Check validate:work ratio**: High ratios indicate validation loops

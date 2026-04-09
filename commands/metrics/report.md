<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Generate full efficiency metrics report comparing baseline vs current performance
---

# Efficiency Metrics Report

## Purpose

Generates a comprehensive report comparing tool efficiency metrics before and after optimization changes (deployed 2026-01-08).

## Data Sources

1. **Project-Agents Output Logs**: `agents/output/*.json` (workflow session logs)
2. **Claude Code Stats**: `~/.claude/stats-cache.json` (built-in metrics)

## Execute

### Option 1: Project-Agents Script (full report with compression/checkpoint stats)

```bash
cd "$PROJECT_ROOT/agents" && python3 scripts/efficiency_metrics.py report
```

### Option 2: Claude Code Stats (quick summary)

```bash
cat ~/.claude/stats-cache.json | python3 -c "
import json, sys
from datetime import datetime

data = json.load(sys.stdin)

print('=' * 60)
print('EFFICIENCY METRICS REPORT')
print(f'Generated: {datetime.now().strftime(\"%Y-%m-%d %H:%M:%S\")}')
print('=' * 60)

# Overall stats
print(f'\n## Overall Usage')
print(f'Total Sessions: {data.get(\"totalSessions\", 0):,}')
print(f'Total Messages: {data.get(\"totalMessages\", 0):,}')
for model, usage in data.get('modelUsage', {}).items():
    print(f'\nModel: {model}')
    print(f'  Output Tokens: {usage.get(\"outputTokens\", 0):,}')
    print(f'  Cache Read: {usage.get(\"cacheReadInputTokens\", 0):,}')

# Baseline: 2025-12-18 to 2026-01-07
baseline_act = [d for d in data.get('dailyActivity', []) if '2025-12-18' <= d['date'] <= '2026-01-07']
baseline_tok = [d for d in data.get('dailyModelTokens', []) if '2025-12-18' <= d['date'] <= '2026-01-07']
b_sessions = sum(d['sessionCount'] for d in baseline_act)
b_tokens = sum(sum(d['tokensByModel'].values()) for d in baseline_tok)
b_tools = sum(d['toolCallCount'] for d in baseline_act)
b_msgs = sum(d['messageCount'] for d in baseline_act)

print(f'\n## Baseline (Dec 18 - Jan 7)')
print(f'| Metric | Total | Per Session |')
print(f'|--------|-------|-------------|')
print(f'| Sessions | {b_sessions} | - |')
print(f'| Tokens | {b_tokens:,} | {b_tokens/b_sessions:,.0f} |' if b_sessions else '| Tokens | 0 | - |')
print(f'| Tool Calls | {b_tools:,} | {b_tools/b_sessions:.1f} |' if b_sessions else '| Tool Calls | 0 | - |')

# Current: 2026-01-08 onwards
current_act = [d for d in data.get('dailyActivity', []) if d['date'] >= '2026-01-08']
current_tok = [d for d in data.get('dailyModelTokens', []) if d['date'] >= '2026-01-08']
c_sessions = sum(d['sessionCount'] for d in current_act)
c_tokens = sum(sum(d['tokensByModel'].values()) for d in current_tok)
c_tools = sum(d['toolCallCount'] for d in current_act)

print(f'\n## Current (Jan 8+)')
print(f'| Metric | Total | Per Session |')
print(f'|--------|-------|-------------|')
print(f'| Sessions | {c_sessions} | - |')
print(f'| Tokens | {c_tokens:,} | {c_tokens/c_sessions:,.0f} |' if c_sessions else '| Tokens | 0 | - |')
print(f'| Tool Calls | {c_tools:,} | {c_tools/c_sessions:.1f} |' if c_sessions else '| Tool Calls | 0 | - |')

# Comparison
if b_sessions and c_sessions:
    b_avg = b_tokens / b_sessions
    c_avg = c_tokens / c_sessions
    change = ((c_avg - b_avg) / b_avg * 100)
    symbol = '✅' if change < -10 else '❌' if change > 5 else '➖'
    print(f'\n## Comparison')
    print(f'{symbol} Tokens/Session: {change:+.1f}%')
    print(f'   Baseline: {b_avg:,.0f} → Current: {c_avg:,.0f}')

# 7-day trend
print(f'\n## 7-Day Trend')
recent = data.get('dailyActivity', [])[-7:]
tokens_recent = {d['date']: sum(d['tokensByModel'].values()) for d in data.get('dailyModelTokens', [])[-7:]}
print(f'| Date | Sessions | Tokens | Tool Calls |')
print(f'|------|----------|--------|------------|')
for day in recent:
    toks = tokens_recent.get(day['date'], 0)
    print(f'| {day[\"date\"]} | {day[\"sessionCount\"]} | {toks:,} | {day[\"toolCallCount\"]:,} |')

print('\n' + '=' * 60)
"
```

## What Gets Tracked

| Metric | Description |
|--------|-------------|
| Token Usage | Input, output, cache read/write per session |
| Tool Result Sizes | Character counts before/after compression |
| Compression Savings | From result-compressor.py hook |
| Checkpoint Usage | Workflow resumability statistics |
| Cost by Command | USD cost breakdown for all 35+ tracked commands |
| Workflow Patterns | Pattern training stats from workflow-pattern-trainer.py |
| Skill Executions | Success/failure tracking for all skill invocations |

## Tracked Commands

All agents commands are instrumented:

**Core Workflow**: work, validate, implement, create-implementation-plan, review, fix-pr, resolve-pr

**Epic Lifecycle**: plan, groom, validate-plan, validate-groom

**Creation**: next, issue, bug, change

**Analysis**: audit, investigate, garden, garden-accuracy, garden-cache, garden-readiness, garden-relevancy, sequence, sequence-json

**Utility**: consolidate-prs, update-docs, reclaim, fix-pipeline

**Loop**: loop:issue, loop:epic, loop:backlog

**Metrics**: metrics:baseline, metrics:current, metrics:compare, metrics:report, metrics:before-after

**Integration**: agentdb-integration

## Skill Tracking

Skills invoked via the Skill tool are tracked at `~/.claude/skill-tracking/executions.jsonl`:

```bash
# View skill execution stats
python3 ~/.claude/hooks/skill-tracker.py stats
```

## Related Commands

| Command | Purpose |
|---------|---------|
| `/metrics:baseline` | View pre-change metrics only |
| `/metrics:current` | View post-change metrics only |
| `/metrics:compare` | Side-by-side comparison |

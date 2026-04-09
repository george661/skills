<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Compare baseline vs current metrics side-by-side
---

# Compare Metrics

## Purpose

Provides a side-by-side comparison of efficiency metrics before and after optimization changes.

## Data Sources

1. **Project-Agents Output Logs**: `agents/output/*.json` (workflow session logs)
2. **Claude Code Stats**: `~/.claude/stats-cache.json` (built-in metrics)

## Execute

### Option 1: Project-Agents Script (workflow logs)

```bash
cd "$PROJECT_ROOT/agents" && python3 scripts/efficiency_metrics.py compare
```

### Option 2: Claude Code Stats (all sessions)

```bash
cat ~/.claude/stats-cache.json | python3 -c "
import json, sys
data = json.load(sys.stdin)

# Baseline: 2025-12-18 to 2026-01-07
baseline_act = [d for d in data.get('dailyActivity', []) if '2025-12-18' <= d['date'] <= '2026-01-07']
baseline_tok = [d for d in data.get('dailyModelTokens', []) if '2025-12-18' <= d['date'] <= '2026-01-07']
b_sessions = sum(d['sessionCount'] for d in baseline_act)
b_tokens = sum(sum(d['tokensByModel'].values()) for d in baseline_tok)
b_tools = sum(d['toolCallCount'] for d in baseline_act)

# Current: 2026-01-08 onwards
current_act = [d for d in data.get('dailyActivity', []) if d['date'] >= '2026-01-08']
current_tok = [d for d in data.get('dailyModelTokens', []) if d['date'] >= '2026-01-08']
c_sessions = sum(d['sessionCount'] for d in current_act)
c_tokens = sum(sum(d['tokensByModel'].values()) for d in current_tok)
c_tools = sum(d['toolCallCount'] for d in current_act)

# Calculate averages
b_avg_tok = b_tokens / b_sessions if b_sessions else 0
c_avg_tok = c_tokens / c_sessions if c_sessions else 0
b_avg_tools = b_tools / b_sessions if b_sessions else 0
c_avg_tools = c_tools / c_sessions if c_sessions else 0

# Calculate change %
tok_change = ((c_avg_tok - b_avg_tok) / b_avg_tok * 100) if b_avg_tok else 0
tool_change = ((c_avg_tools - b_avg_tools) / b_avg_tools * 100) if b_avg_tools else 0

print('## Metrics Comparison')
print()
print(f'| Metric | Baseline | Current | Change |')
print(f'|--------|----------|---------|--------|')
print(f'| Sessions | {b_sessions} | {c_sessions} | - |')
print(f'| Avg Tokens/Session | {b_avg_tok:,.0f} | {c_avg_tok:,.0f} | {tok_change:+.1f}% |')
print(f'| Avg Tools/Session | {b_avg_tools:.1f} | {c_avg_tools:.1f} | {tool_change:+.1f}% |')
"
```

## Comparison Formula

```
Change % = ((current - baseline) / baseline) * 100
```

## Interpretation

| Symbol | Meaning |
|--------|---------|
| Negative % | Improvement (using less) |
| Positive % | Regression (using more) |

## Coverage

All 35+ agents commands are now tracked:

- `/metrics:before-after` provides the most comprehensive per-command cost comparison
- Skill executions are tracked separately in `~/.claude/skill-tracking/`
- Pattern training data in `~/.claude/pattern-training/`

## Related Commands

| Command | Purpose |
|---------|---------|
| `/metrics:report` | Full report with all sections |
| `/metrics:baseline` | Pre-change metrics only |
| `/metrics:current` | Post-change metrics only |

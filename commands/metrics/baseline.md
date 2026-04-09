<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Analyze baseline (pre-optimization) session metrics
---

# Baseline Metrics

## Purpose

Analyzes session metrics from **before** the tool efficiency optimizations were deployed (pre-2026-01-08).

This establishes the baseline for measuring improvement.

## Data Sources

1. **Project-Agents Output Logs**: `agents/output/*.json` (workflow session logs)
2. **Claude Code Stats**: `~/.claude/stats-cache.json` (built-in metrics)

## Execute

### Option 1: Project-Agents Script (workflow logs)

```bash
cd "$PROJECT_ROOT/agents" && python3 scripts/efficiency_metrics.py baseline
```

### Option 2: Claude Code Stats (all sessions)

```bash
cat ~/.claude/stats-cache.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
# Filter for 2025-12-18 to 2026-01-07 (baseline period)
baseline = [d for d in data.get('dailyActivity', []) if '2025-12-18' <= d['date'] <= '2026-01-07']
sessions = sum(d['sessionCount'] for d in baseline)
messages = sum(d['messageCount'] for d in baseline)
tools = sum(d['toolCallCount'] for d in baseline)
tokens_data = [d for d in data.get('dailyModelTokens', []) if '2025-12-18' <= d['date'] <= '2026-01-07']
tokens = sum(sum(d['tokensByModel'].values()) for d in tokens_data)
print(f'Sessions: {sessions}')
print(f'Messages: {messages:,}')
print(f'Tool Calls: {tools:,}')
print(f'Total Tokens: {tokens:,}')
print(f'Avg Tokens/Session: {tokens/sessions:,.0f}' if sessions else 'N/A')
print(f'Tool Calls/Message: {tools/messages:.3f}' if messages else 'N/A')
"
```

## Baseline Period

- **Start**: 2025-12-18 (when efficiency tracking began)
- **End**: 2026-01-07 (day before optimizations)

## Instrumentation

As of 2026-01-14, all 35+ agents commands are instrumented:

- Cost tracking: `output/costs.jsonl` (via cost-capture.py hook)
- Pattern training: `~/.claude/pattern-training/` (via workflow-pattern-trainer.py)
- Skill tracking: `~/.claude/skill-tracking/` (via skill-tracker.py)

## Related Commands

| Command | Purpose |
|---------|---------|
| `/metrics:report` | Full comparison report |
| `/metrics:current` | Post-change metrics |
| `/metrics:compare` | Side-by-side comparison |

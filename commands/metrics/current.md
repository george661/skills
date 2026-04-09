<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Analyze current (post-optimization) session metrics
---

# Current Metrics

## Purpose

Analyzes session metrics from **after** the tool efficiency optimizations were deployed (post-2026-01-08).

## Data Sources

1. **Project-Agents Output Logs**: `agents/output/*.json` (workflow session logs)
2. **Claude Code Stats**: `~/.claude/stats-cache.json` (built-in metrics)

## Execute

### Option 1: Project-Agents Script (workflow logs)

```bash
cd "$PROJECT_ROOT/agents" && python3 scripts/efficiency_metrics.py current
```

### Option 2: Claude Code Stats (all sessions)

```bash
cat ~/.claude/stats-cache.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
# Filter for 2026-01-08 onwards
current = [d for d in data.get('dailyActivity', []) if d['date'] >= '2026-01-08']
sessions = sum(d['sessionCount'] for d in current)
messages = sum(d['messageCount'] for d in current)
tools = sum(d['toolCallCount'] for d in current)
tokens_data = [d for d in data.get('dailyModelTokens', []) if d['date'] >= '2026-01-08']
tokens = sum(sum(d['tokensByModel'].values()) for d in tokens_data)
print(f'Sessions: {sessions}')
print(f'Messages: {messages:,}')
print(f'Tool Calls: {tools:,}')
print(f'Total Tokens: {tokens:,}')
print(f'Avg Tokens/Session: {tokens/sessions:,.0f}' if sessions else 'N/A')
print(f'Tool Calls/Message: {tools/messages:.3f}' if messages else 'N/A')
"
```

## Optimizations Being Measured

1. **Field Selection** - Only requesting needed fields from Jira/Bitbucket APIs
2. **Result Compression** - Truncating large MCP tool results (max 8K chars, 20 items)
3. **Checkpointing** - Resumable workflows reducing re-work
4. **Per-Tool Examples** - Minimal context loading for tool patterns

## Expected Improvements

| Metric | Expected Change |
|--------|-----------------|
| Token Usage | -30% to -50% |
| Tool Result Size | -60% to -80% |

## Tracked Commands (35+)

All agents commands are now instrumented for cost and pattern tracking:

- **Core Workflow**: work, validate, implement, review, fix-pr, resolve-pr
- **Epic Lifecycle**: plan, groom, validate-plan, validate-groom
- **Creation**: next, issue, bug, change
- **Analysis**: audit, investigate, garden, garden-*, sequence
- **Utility**: consolidate-prs, update-docs, reclaim, fix-pipeline
- **Loops**: loop:issue, loop:epic, loop:backlog
- **Metrics**: All metrics:* commands

## Skill Tracking

Skills invoked via the Skill tool are tracked separately:
- Location: `~/.claude/skill-tracking/executions.jsonl`
- Stats: `python3 ~/.claude/hooks/skill-tracker.py stats`

## Related Commands

| Command | Purpose |
|---------|---------|
| `/metrics:report` | Full comparison report |
| `/metrics:baseline` | Pre-change metrics |
| `/metrics:compare` | Side-by-side comparison |

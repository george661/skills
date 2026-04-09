<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Compare cost, speed, and success rate across models (cloud vs local)
---

# Model Metrics

## Purpose

Shows per-model and per-model-per-command metrics from AgentDB. Use this to compare cloud model costs against local model performance and tune the routing strategy.

## Arguments

- `$ARGUMENTS` — Optional: `by_command` to break down per model+command, or a JSON filter like `{"since": "2026-03-01", "command": "implement"}`

## Execute

### Step 1: Parse Arguments

Determine the aggregation mode and any filters from `$ARGUMENTS`:

- If empty or `models`: aggregate `by_model`
- If `by_command`: aggregate `by_model_command`
- If JSON string: parse and use as filter, default aggregate `by_model`

### Step 2: Query AgentDB

```bash
# Default: by_model aggregation
npx tsx ~/.claude/skills/agentdb/metrics_query.ts '{"aggregate": "by_model", "limit": 100}'
```

Or with command breakdown:

```bash
npx tsx ~/.claude/skills/agentdb/metrics_query.ts '{"aggregate": "by_model_command", "limit": 200}'
```

Or with filters (merge $ARGUMENTS JSON with aggregate):

```bash
npx tsx ~/.claude/skills/agentdb/metrics_query.ts '{"aggregate": "by_model", "limit": 100, "since": "...", "command": "..."}'
```

### Step 3: Format Report

Present results as a markdown table with these columns:

| Model/Tier | Sessions | Total Cost | Avg Cost | Avg Tokens | Avg Latency | Success Rate | Local? |
|-----------|----------|-----------|---------|-----------|------------|-------------|--------|

**Highlight key comparisons:**
- Cloud vs local cost difference
- Success rate gaps that might warrant tier reassignment
- Latency differences (local models trade cost for speed)
- Any models with unusually high failure rates

### Step 4: Routing Recommendations

Based on the data, suggest:
1. Commands where local models are performing well (keep on local)
2. Commands where local models have low success rate (consider promoting to cloud)
3. Cost savings achieved vs all-cloud baseline
4. Any anomalies worth investigating

## Example Output

```
## Model Performance Summary

| Model | Sessions | Total Cost | Avg Cost | Success Rate | Local |
|-------|----------|-----------|---------|-------------|-------|
| opus  | 12       | $45.30    | $3.78   | 100%        | No    |
| sonnet | 28      | $22.40    | $0.80   | 96%         | No    |
| qwen3:32b | 45   | $0.00     | $0.00   | 89%         | Yes   |
| qwen3:8b | 120   | $0.00     | $0.00   | 95%         | Yes   |

### Cloud vs Local
- Cloud sessions: 40 ($67.70 total)
- Local sessions: 165 ($0.00 total)
- Estimated savings: $132.00 (66% of sessions moved to local)

### Attention Needed
- qwen3:32b success rate on `implement` is 82% — consider Sonnet fallback
- glm-4.7-flash tool_call failures on Jira queries — investigate
```

## Related Commands

| Command | Purpose |
|---------|---------|
| `/metrics:report` | Full metrics report |
| `/metrics:current` | Current session metrics |
| `/metrics:compare` | Baseline vs current comparison |
| `/metrics:before-after` | Per-command cost comparison |

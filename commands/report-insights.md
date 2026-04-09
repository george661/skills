---
description: "Correlate loop-metrics with weekly reports and write workflow insights."
model_tier: haiku
dispatch: true
---

# /report-insights

Reads Claude Code session JSONL files from `~/.claude/projects/` and daily
report files. Produces tool/command usage analysis and workflow correlation findings.

## Usage

    /report-insights                 # current ISO week
    /report-insights --week=2026-W12 # specific week

## Steps

Run:

```bash
npx tsx ~/.claude/skills/report-insights/generate.ts [--week=YYYY-WW]
```

Output: `$DAILY_REPORTS_PATH/insights/YYYY-WW.md`

## What it produces

- Work type classification table (Infrastructure / Planning / Feature / Bug / Tooling)
- Session & cost summary (tokens, cache hit rate, estimated cost)
- Command pipeline funnel with completion rates
- Tool call distribution (flags Bash > 60% as actionable)
- Model usage split
- Correlation findings with data, narrative, and implication for each
- Action summary table with severity

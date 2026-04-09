---
description: "Generate the weekly work summary for the last 7 days."
model_tier: haiku
dispatch: true
---

# /weekly-report

Generates the weekly digest combining fresh analysis (git, Jira, BOMs) with a
cross-check against the 7 existing daily report files.

## Usage

    /weekly-report                    # current ISO week
    /weekly-report --week=2026-W12    # specific week (ISO format)

## Steps

Run:

```bash
npx tsx ~/.claude/skills/weekly-report/generate.ts [--week=YYYY-WW]
```

Output: `$DAILY_REPORTS_PATH/YYYY-WW.md` (e.g. `2026-W13.md`)

If `DAILY_REPORTS_PATH` is not set, defaults to `$PROJECT_ROOT/daily-reports`.

## Phases

**Phase 1 — Fresh analysis**: Queries git log, Jira (issues transitioned to Done
in the window), and BOMs across the full 7-day window.

**Phase 2 — Cross-check**: Reads existing daily `.md` files, extracts commit and
issue counts, and notes any discrepancy > 10% against the fresh data.

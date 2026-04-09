---
description: Generate a daily report of work accomplished from git history, Jira, and deployment BOMs. Schedule runs automatically at 10pm via launchd.
arguments:
  - name: flags
    description: "Optional: --force (overwrite today's report if it exists)"
    required: false
---

# Daily Report

Generate a daily summary of work accomplished, deployments across all environments, and items that remain incomplete.

The report covers the period since the last report was generated (or 24 hours if no prior report exists).

## Execute

```bash
npx tsx ~/.claude/skills/daily-report/generate.ts $ARGUMENTS.flags
```

## Output

The report is written to `$DAILY_REPORTS_PATH/YYYY-MM-DD.md`.

## Reading the Report

When asked to read the daily report, look in `$DAILY_REPORTS_PATH` for the most recent `.md` file, read it, and identify all `- [ ]` items under **Next / Incomplete** to determine what needs attention.

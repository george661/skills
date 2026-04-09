<!-- MODEL_TIER: haiku -->
---
description: Validate all Jira issues in VALIDATION status sequentially
arguments:
  - name: max_issues
    description: Maximum number of issues to validate (default 10)
    required: false
---

# Validate All Issues in VALIDATION Status

## Purpose

Discovers all Jira issues currently in VALIDATION status and runs `/validate` on each.
Each `/validate` invocation is an Opus orchestrator that dispatches its own sub-commands
to local models — the actual work is cheap, only the orchestration runs on Opus.

## Phase 1: Discover Issues

### 1a: awaiting-deploy issues first (priority)
```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${TENANT_PROJECT} AND status = VALIDATION AND labels = \"step:awaiting-deploy\" ORDER BY updated ASC", "fields": ["key", "summary", "status", "labels", "priority"]}'
```

Re-check deployment status for these. If deployed since last check, proceed with full validation.
If awaiting-deploy >7 days, set verdict to NEEDS_HUMAN.

### 1b: needs-revalidation issues
```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${TENANT_PROJECT} AND status = VALIDATION AND labels = \"needs-revalidation\" ORDER BY updated ASC", "fields": ["key", "summary", "status", "labels", "priority"]}'
```

### 1c: remaining VALIDATION issues
```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${TENANT_PROJECT} AND status = VALIDATION AND labels != \"step:awaiting-deploy\" ORDER BY updated ASC", "fields": ["key", "summary", "status", "labels", "priority"]}'
```

Merge, deduplicate. Priority: awaiting-deploy → needs-revalidation → oldest first.
Cap at `$ARGUMENTS.max_issues` (default 10).

If no issues found, report "No issues in VALIDATION status" and stop.

Print the list:
```
Found <N> issues in VALIDATION:
| Key | Summary | Priority | Labels |
|-----|---------|----------|--------|
| PROJ-123 | ... | High | step:awaiting-deploy |
```

## Phase 2: Run Validations Sequentially

For each issue:

1. Record start time:
   ```bash
   START_TIME=$(date +%s)
   ```

2. Invoke `/validate`:
   ```
   /validate <issue-key>
   ```

Each `/validate` is a full Opus orchestrator session that:
- Checks deployment status (dispatched to local)
- Runs tests (dispatched to local)
- Collects evidence (dispatched to local)
- Evaluates results (inline Opus)
- Transitions Jira (inline Opus)

**Run sequentially, not in parallel.** Each `/validate` invocation spawns its own local model
dispatches. Running multiple in parallel would overload Ollama.

3. Record end time and check duration:
   ```bash
   END_TIME=$(date +%s)
   DURATION=$((END_TIME - START_TIME))
   ```

4. If duration < 180 seconds (3 minutes), log a warning:
   ```
   WARNING: <issue-key> validated in <DURATION>s — may have insufficient evidence.
   ```
   This is informational only (no artificial sleep). Fast validations are flagged
   in the summary for human review.

5. After each `/validate` completes, print progress:
   ```
   [<N>/<total>] <issue-key>: <verdict> (<DONE/TODO/NEEDS_DEPLOY/NEEDS_HUMAN>) [<DURATION>s]
   ```

6. Remove `needs-revalidation` label if present:
   ```bash
   npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "<issue-key>", "update": {"labels": [{"remove": "needs-revalidation"}]}}'
   ```

## Phase 3: Summary

```
## Batch Validation Complete

| Issue | Verdict | New Status | Duration | Evidence Quality |
|-------|---------|------------|----------|------------------|
| PROJ-123 | PASS | Done | 5m 23s | STRONG |
| PROJ-124 | FAIL | To Do | 3m 12s | SUFFICIENT |
| PROJ-125 | NEEDS_DEPLOY | Validation | 1m 45s | N/A |
| PROJ-126 | NEEDS_HUMAN | Validation | 2m 01s | INSUFFICIENT |

**Validated:** <N>
**Passed:** <M>
**Failed:** <K>
**Needs Deploy:** <J>
**Escalated:** <L>
**Fast validations (<3min):** <F>
**Average duration:** <avg>s
**Total wall-clock time:** <total>
```

**START NOW: Begin Phase 1.**

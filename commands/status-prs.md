<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->

---
description: Show all open PRs across all repos with build status and commits behind merge target
---

# PR Status Dashboard

## Step 1: Fetch PR Status

```bash
npx tsx ~/.claude/skills/bitbucket/pr_status.ts '{}'
```

## Step 2: Present Results

Parse the JSON array output and display a formatted summary.

### Grouping and Sort Order

Group PRs by build status in this order:
1. `FAILED` - needs immediate attention
2. `INPROGRESS` - builds running
3. `NO_BUILDS` / `unknown` - no CI signal
4. `SUCCESSFUL` - healthy

Within each group, sort by `commits_behind` descending (most stale first).

### Status Indicators

| build_status | Icon |
|---|---|
| FAILED | ❌ |
| INPROGRESS | 🔄 |
| SUCCESSFUL | ✅ |
| NO_BUILDS | ⚠️ |
| unknown | ❓ |

### Behind Indicator

- `0` → `up to date`
- `1-5` → `{n} behind`
- `6+` → `**{n} behind**` (bold, needs rebase)
- `unknown` → `? behind`

### Output Format

```
Open PRs across all repos  ({total} total)
══════════════════════════════════════════

❌ FAILED ({count})
  [{repo}] PR #{pr_id} — {title}
  Author: {author}  |  {source_branch} → {destination_branch}  |  {commits_behind indicator}
  {url}

🔄 IN PROGRESS ({count})
  ...

⚠️ NO BUILDS ({count})
  ...

✅ SUCCESSFUL ({count})
  ...

──────────────────────────────────────────
Summary: {failed} failed, {in_progress} in progress, {no_builds} no builds, {successful} passing
```

If there are no open PRs, output: "No open PRs found across all repos."

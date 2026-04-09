<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Scan and cleanup stale worktrees across all repositories
arguments: []
---

# Cleanup Worktrees

## Purpose

This command scans all repositories in PROJECT_ROOT for stale worktrees and cleans them up using a **three-tier evaluation** that minimizes API calls by checking the cheapest signals first.

**Use this command to:**
- Reclaim disk space from abandoned worktrees
- Clean up after merged PRs
- Remove orphaned worktree directories

---

## Three-Tier Staleness Evaluation

Evaluate each worktree in this order. **Stop as soon as any tier returns STALE.**

| Tier | Check | Cost | Short-circuits |
|------|-------|------|----------------|
| 1 | Git merge state vs origin/main | Free (local git) | If branch is merged into main |
| 2 | Bitbucket/GitHub PR state | 1 API call | If PR is MERGED or DECLINED |
| 3 | Jira issue status | 1 API call | If issue is Done/Closed/Cancelled |

A worktree is **ACTIVE** only if all three tiers say it's not stale.

---

## Step 1: Scan All Repositories

### 1.1 Get List of Repositories

```bash
# Get all directories in PROJECT_ROOT that contain .git
for repo_path in ${PROJECT_ROOT}/*/; do
  if [ -d "${repo_path}.git" ]; then
    echo "$repo_path"
  fi
done
```

### 1.2 Fetch Latest from All Remotes

```bash
# Fetch once per repo to have up-to-date remote state
cd <repo-path>
git fetch origin main --prune
```

### 1.3 For Each Repository, List Worktrees

```bash
cd <repo-path>
git worktree list --porcelain
```

Filter out the main repo worktree (the one on `refs/heads/main`). Only evaluate worktrees under `${PROJECT_ROOT}/worktrees/`.

### 1.4 Extract Metadata

For each worktree:

```bash
branch_name=$(git -C <worktree-path> rev-parse --abbrev-ref HEAD)
issue_key=$(echo "$branch_name" | grep -oE '(PROJ|DEPT|TECH)-[0-9]+')
repo_name=$(basename <repo-path>)
```

---

## Step 2: Tiered Staleness Evaluation

For each worktree (excluding main), evaluate tiers in order:

### Tier 1: Git Merge State (FREE)

```bash
cd <repo-path>
# Check if the worktree branch is fully merged into origin/main
git merge-base --is-ancestor <worktree-branch> origin/main
```

- **Exit code 0** → Branch is merged into main → **STALE** (stop, skip Tier 2 and 3)
- **Exit code 1** → Branch is NOT merged → proceed to Tier 2

### Tier 2: Bitbucket PR State (1 API call)

Only run if Tier 1 says NOT MERGED.

```bash
# Search for PRs from this branch
npx tsx ~/.claude/skills/bitbucket/list_pull_requests.ts '{"repo_slug": "<repo-name>", "state": "MERGED", "source_branch": "'$branch_name'"}'
```

Also check DECLINED state:

```bash
npx tsx ~/.claude/skills/bitbucket/list_pull_requests.ts '{"repo_slug": "<repo-name>", "state": "DECLINED", "source_branch": "'$branch_name'"}'
```

- **PR found with state MERGED or DECLINED** → **STALE** (stop, skip Tier 3)
- **PR found with state OPEN** → **ACTIVE** (stop, this is in-progress work)
- **No PR found** → proceed to Tier 3

### Tier 3: Jira Issue Status (1 API call)

Only run if Tier 1 and 2 are inconclusive.

```bash
if [ -n "$issue_key" ]; then
  npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "'$issue_key'", "fields": ["status", "summary"]}'
fi
```

- **Status = Done, Closed, Cancelled** → **STALE**
- **Status = anything else** → **ACTIVE**
- **No issue key extractable** → **ACTIVE** (keep, requires manual review)

---

## Step 3: Delete Stale Worktrees

For each worktree marked STALE:

### 3.1 Remove Worktree

```bash
cd <repo-path>

# Remove worktree (force if needed for uncommitted changes)
git worktree remove --force <worktree-path>

# Prune worktree metadata
git worktree prune

# Delete local branch if it exists
git branch -D "$branch_name" 2>/dev/null || true
```

### 3.2 Batch Prune

After all deletions for a repo:

```bash
git worktree prune
```

---

## Step 4: Report Summary

### 4.1 Generate Cleanup Report

```markdown
## Worktree Cleanup Summary

**Scan Date:** <timestamp>
**Repositories Scanned:** <count>

### Evaluation Efficiency

| Tier | Check | Stale Found | API Calls |
|------|-------|:-----------:|:---------:|
| 1 | Git merge-base | <count> | 0 |
| 2 | Bitbucket PR | <count> | <count> |
| 3 | Jira status | <count> | <count> |

### Cleaned Up

| Repository | Issue | Branch | Tier | Reason |
|------------|-------|--------|:----:|--------|
| api-service | PROJ-123 | PROJ-123-desc | 1 | Merged into main |
| frontend-app | PROJ-456 | PROJ-456-desc | 2 | PR merged |
| frontend-app | PROJ-789 | PROJ-789-desc | 3 | Issue Done |

**Total Worktrees Deleted:** <count>

### Active Worktrees (Kept)

| Repository | Issue | Branch | Jira Status |
|------------|-------|--------|-------------|
| api-service | PROJ-999 | PROJ-999-desc | In Progress |

**Total Active Worktrees:** <count>

### Errors

${errors.length > 0 ? errors.map(e => `- ${e}`).join('\n') : 'None'}
```

### 4.2 Store Cleanup Results in Memory

```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{
  "session_id": "${TENANT_NAMESPACE}",
  "task": "worktree-cleanup",
  "reward": 0.9,
  "success": true
}'
```

---

## Anti-Patterns (AUTOMATIC FAILURE)

- Deleting worktree for an OPEN PR = FAILURE
- Deleting main repository worktree = FAILURE
- Not handling errors gracefully = FAILURE
- Making API calls before checking git merge state = FAILURE (violates tier order)
- Checking Jira before checking Bitbucket = FAILURE (violates tier order)

---

**START NOW: Begin Step 1 (scan), then evaluate each worktree through the tiers.**

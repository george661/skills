<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->

---
description: Reset a Jira issue to clean state for re-testing (clears checkpoints, worktree, branches, labels, transitions to To Do)
---

# Scrub Issue: $ARGUMENTS

Reset issue **$ARGUMENTS** to a pristine state so it can be re-run through `/work`.

## Inputs

- **Issue key**: `$ARGUMENTS` (e.g., `PROJ-730`)
- If `$ARGUMENTS` is empty, ask the user for an issue key.

## Step 1: Clear Checkpoints

```bash
python3 ~/.claude/hooks/checkpoint.py clear "$ARGUMENTS" 2>/dev/null || true
```

Report how many checkpoints were cleared (or "none found").

## Step 2: Identify Repository

Auto-detect the repo from the issue title prefix (text in brackets):

```bash
npx tsx ~/.claude/skills/issues/get_issue.ts "{\"issue_key\": \"$ARGUMENTS\", \"fields\": \"summary\"}"
```

Extract repo slug from `[repo-name]` prefix in the summary. If no brackets, ask the user which repo.

Store as `REPO` and `ISSUE_LOWER` (lowercase issue key) for remaining steps.

## Step 3: Remove Worktree

Check for and remove the worktree at `~/dev/gw/worktrees/{REPO}-{ISSUE_LOWER}`:

```bash
WORKTREE_DIR="${HOME}/dev/gw/worktrees/${REPO}-${ISSUE_LOWER}"
if [ -d "$WORKTREE_DIR" ]; then
  git -C "${HOME}/dev/gw/${REPO}" worktree remove "$WORKTREE_DIR" --force 2>/dev/null || rm -rf "$WORKTREE_DIR"
fi
```

Report whether a worktree was found and removed.

## Step 4: Delete Branches (Local + Remote)

In the repo directory `~/dev/gw/{REPO}`:

1. Switch to default branch if currently on the issue branch
2. Delete all local branches matching `*{ISSUE_LOWER}*` or `*{ISSUE}*`
3. Delete all remote branches matching the same patterns

```bash
REPO_DIR="${HOME}/dev/gw/${REPO}"
DEFAULT_BRANCH=$(git -C "$REPO_DIR" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||' || echo "main")
CURRENT=$(git -C "$REPO_DIR" branch --show-current 2>/dev/null || true)

# Switch off issue branch if needed
if [[ "$CURRENT" == *"${ISSUE_LOWER}"* ]] || [[ "$CURRENT" == *"$ARGUMENTS"* ]]; then
  git -C "$REPO_DIR" checkout "$DEFAULT_BRANCH"
fi

# Local branches
for b in $(git -C "$REPO_DIR" branch --list "*${ISSUE_LOWER}*" "*${ARGUMENTS}*" 2>/dev/null | sed 's/^[* ]*//'); do
  git -C "$REPO_DIR" branch -D "$b" 2>/dev/null || true
done

# Remote branches
for b in $(git -C "$REPO_DIR" branch -r --list "*${ISSUE_LOWER}*" "*${ARGUMENTS}*" 2>/dev/null | sed 's|origin/||' | sed 's/^[* ]*//'); do
  git -C "$REPO_DIR" push origin --delete "$b" 2>/dev/null || true
done
```

Report branches deleted (local and remote counts).

## Step 5: Clear All Labels

```bash
cd ~/.claude/skills/jira && npx tsx -e "
import { jiraRequest } from './jira-client.ts';
async function main() {
  await jiraRequest('PUT', '/rest/api/3/issue/$ARGUMENTS', { fields: { labels: [] } });
  console.log('Labels cleared');
}
main();
"
```

## Step 6: Transition to To Do

```bash
npx tsx ~/.claude/skills/issues/transition_issue.ts "{\"issue_key\": \"$ARGUMENTS\", \"transition_id\": \"11\"}"
```

If transition fails, the issue may already be in To Do — that's fine.

## Step 7: Clear Workflow State Cache

```bash
npx tsx ~/.claude/skills/agentdb/workflow_state_upsert.ts "{\"issue_key\": \"$ARGUMENTS\", \"updates\": {\"status\": \"To Do\", \"step_label\": \"\", \"outcome_label\": \"\"}}" 2>/dev/null || true
```

## Step 8: Verify

Fetch the issue and confirm:

```bash
npx tsx ~/.claude/skills/issues/get_issue.ts "{\"issue_key\": \"$ARGUMENTS\", \"fields\": \"summary,status,labels\"}"
```

Display:
- Status (should be "To Do")
- Labels (should be empty `[]`)
- Checkpoint count (should be 0)

## Summary

Print a summary table:

| Item | Result |
|------|--------|
| Checkpoints | Cleared |
| Worktree | Removed / Not found |
| Local branches | N deleted |
| Remote branches | N deleted |
| Labels | Cleared |
| Status | To Do |
| Workflow cache | Reset |

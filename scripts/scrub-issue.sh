#!/usr/bin/env bash
# scrub-issue.sh — Reset a Jira issue to a clean state for re-testing
#
# Clears: checkpoints, worktree, branches, labels, transitions to To Do
#
# Usage: ./scrub-issue.sh PROJ-730 [repo-slug]
#   repo-slug defaults to auto-detect from issue title prefix

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: scrub-issue.sh <issue-key> [repo-slug]"
  exit 1
fi

ISSUE="$1"
REPO="${2:-}"
ISSUE_LOWER="$(echo "$ISSUE" | tr '[:upper:]' '[:lower:]')"
PROJECT_ROOT="${HOME}/dev/gw"

echo "=== Scrubbing $ISSUE ==="

# 1. Clear checkpoints
echo "[1/5] Clearing checkpoints..."
python3 ~/.claude/hooks/checkpoint.py clear "$ISSUE" 2>/dev/null || true

# 2. Auto-detect repo from issue title if not provided
if [ -z "$REPO" ]; then
  REPO=$(npx tsx ~/.claude/skills/jira/get_issue.ts "{\"issue_key\": \"$ISSUE\", \"fields\": \"summary\"}" 2>/dev/null \
    | python3 -c "import sys,json; s=json.load(sys.stdin).get('fields',{}).get('summary',''); r=s.split(']')[0].lstrip('[') if ']' in s else ''; print(r)" 2>/dev/null || true)
  [ -n "$REPO" ] && echo "  Auto-detected repo: $REPO"
fi

# 3. Remove worktree
WORKTREE_DIR="${PROJECT_ROOT}/worktrees/${REPO}-${ISSUE_LOWER}"
if [ -d "$WORKTREE_DIR" ]; then
  echo "[2/5] Removing worktree: $WORKTREE_DIR"
  git -C "${PROJECT_ROOT}/${REPO}" worktree remove "$WORKTREE_DIR" --force 2>/dev/null || rm -rf "$WORKTREE_DIR"
else
  echo "[2/5] No worktree found"
fi

# 4. Delete branches (local + remote)
echo "[3/5] Cleaning branches..."
if [ -n "$REPO" ] && [ -d "${PROJECT_ROOT}/${REPO}" ]; then
  # Switch to main/default branch first so we can delete the issue branch
  DEFAULT_BRANCH=$(git -C "${PROJECT_ROOT}/${REPO}" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||' || echo "main")
  CURRENT_BRANCH=$(git -C "${PROJECT_ROOT}/${REPO}" branch --show-current 2>/dev/null || true)
  if [[ "$CURRENT_BRANCH" == *"${ISSUE_LOWER}"* ]] || [[ "$CURRENT_BRANCH" == *"${ISSUE}"* ]]; then
    echo "  Switching from $CURRENT_BRANCH to $DEFAULT_BRANCH..."
    git -C "${PROJECT_ROOT}/${REPO}" checkout "$DEFAULT_BRANCH" 2>/dev/null || true
  fi
  # Find matching branches
  for branch in $(git -C "${PROJECT_ROOT}/${REPO}" branch --list "*${ISSUE_LOWER}*" "*${ISSUE}*" 2>/dev/null | sed 's/^[* ]*//' || true); do
    echo "  Deleting local: $branch"
    git -C "${PROJECT_ROOT}/${REPO}" branch -D "$branch" 2>/dev/null || true
  done
  for branch in $(git -C "${PROJECT_ROOT}/${REPO}" branch -r --list "*${ISSUE_LOWER}*" "*${ISSUE}*" 2>/dev/null | sed 's|origin/||' | sed 's/^[* ]*//' || true); do
    echo "  Deleting remote: $branch"
    git -C "${PROJECT_ROOT}/${REPO}" push origin --delete "$branch" 2>/dev/null || true
  done
else
  echo "  No repo to clean branches from"
fi

# 5. Clear labels — call jira-client from its own directory so imports resolve
echo "[4/5] Clearing labels..."
cd ~/.claude/skills/jira
npx tsx -e "
import { jiraRequest } from './jira-client.ts';
async function main() {
  await jiraRequest('PUT', '/rest/api/3/issue/$ISSUE', { fields: { labels: [] } });
  console.log('  Labels cleared');
}
main();
" 2>/dev/null || echo "  Label clear failed"
cd - >/dev/null

# 6. Transition to To Do
echo "[5/5] Transitioning to To Do..."
npx tsx ~/.claude/skills/jira/transition_issue.ts "{\"issue_key\": \"$ISSUE\", \"transition_id\": \"11\"}" 2>/dev/null | python3 -c "import sys,json; print('  Done')" 2>/dev/null || echo "  Already in To Do or transition failed"

echo ""
echo "=== $ISSUE scrubbed ==="

# Verify
echo ""
echo "Verification:"
npx tsx ~/.claude/skills/jira/get_issue.ts "{\"issue_key\": \"$ISSUE\", \"fields\": \"summary,status,labels\"}" 2>/dev/null \
  | python3 -c "
import sys, json
f = json.load(sys.stdin).get('fields', {})
print(f'  Status: {f.get(\"status\",{}).get(\"name\",\"?\")}')
print(f'  Labels: {f.get(\"labels\",[])}')
" 2>/dev/null || true
python3 ~/.claude/hooks/checkpoint.py list "$ISSUE" 2>/dev/null | python3 -c "import sys,json; print(f'  Checkpoints: {json.load(sys.stdin).get(\"total\",\"?\")}')" 2>/dev/null || true

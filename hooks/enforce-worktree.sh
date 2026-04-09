#!/bin/bash
#
# enforce-worktree.sh - MANDATORY: Enforces worktree-based workflow for ALL repository work
#
# This hook blocks file modifications unless:
# 1. The agent is working in a git worktree (not the main repo)
# 2. The worktree branch is based on the tip of origin/main
# 3. A PR will be created for the changes (enforced by workflow commands)
#
# This prevents agents from:
# - Accidentally modifying the main repo directly
# - Working on stale branches that could cause merge conflicts
# - Introducing regressions from outdated code
# - Bypassing the PR review process
#
# Configuration:
#   WORKTREE_ENFORCE_REPOS - Regex pattern for repos to enforce (default: all git repos)
#   WORKTREE_WHITELIST_REPOS - Comma-separated list of repos to whitelist (default: none)
#   WORKTREE_WORKSPACE_ROOT - Workspace root path (default: ~/projects)
#

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty')

# Allow operations with no file path
if [[ -z "$FILE_PATH" ]]; then
    echo '{"continue":true}'
    exit 0
fi

# Get absolute path
if [[ "$FILE_PATH" != /* ]]; then
    FILE_PATH="$(pwd)/$FILE_PATH"
fi

# Get directory (create parent check for new files)
DIR=$(dirname "$FILE_PATH")
if [[ ! -d "$DIR" ]]; then
    # For new files, walk up to find existing parent
    PARENT="$DIR"
    while [[ ! -d "$PARENT" ]] && [[ "$PARENT" != "/" ]]; do
        PARENT=$(dirname "$PARENT")
    done
    DIR="$PARENT"
fi

# Change to directory for git operations
cd "$DIR" 2>/dev/null || cd "$(pwd)"

# Check if this is a git repository at all
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    # Not a git repo, allow the operation
    echo '{"continue":true}'
    exit 0
fi

# Get repo info
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
REPO_NAME=$(basename "$REPO_ROOT" 2>/dev/null || echo "")
GIT_DIR=$(git rev-parse --git-dir 2>/dev/null || echo "")

# Load configuration from environment or use defaults
WORKTREE_ENFORCE_REPOS="${WORKTREE_ENFORCE_REPOS:-.*}"
WORKTREE_WHITELIST_REPOS="${WORKTREE_WHITELIST_REPOS:-}"
WORKTREE_WORKSPACE_ROOT="${WORKTREE_WORKSPACE_ROOT:-$HOME/projects}"

# WHITELIST: Allow explicitly whitelisted repos (comma-separated)
# Example: WORKTREE_WHITELIST_REPOS="agents,base-agents,project-docs"
if [[ -n "$WORKTREE_WHITELIST_REPOS" ]]; then
    IFS=',' read -ra WHITELIST <<< "$WORKTREE_WHITELIST_REPOS"
    for WHITELISTED in "${WHITELIST[@]}"; do
        # Trim whitespace
        WHITELISTED=$(echo "$WHITELISTED" | xargs)
        if [[ "$REPO_NAME" == "$WHITELISTED" ]]; then
            echo '{"continue":true}'
            exit 0
        fi
    done
fi

# WHITELIST: Allow *-agents repos (workflow configuration repos can self-modify)
# These repos contain the workflow definitions themselves
if [[ "$REPO_NAME" == *"-agents" ]]; then
    echo '{"continue":true}'
    exit 0
fi

# WHITELIST: Allow *-docs repos (documentation repos don't need PRs for every change)
if [[ "$REPO_NAME" == *"-docs" ]]; then
    echo '{"continue":true}'
    exit 0
fi

# Check if repo matches the enforcement pattern
if [[ ! "$REPO_NAME" =~ $WORKTREE_ENFORCE_REPOS ]]; then
    echo '{"continue":true}'
    exit 0
fi

# Check if we're in a worktree (not the main repo)
# In a worktree, GIT_DIR looks like: /path/to/repo/.git/worktrees/worktree-name
# In main repo, GIT_DIR looks like: /path/to/repo/.git or just .git
if [[ "$GIT_DIR" != *".git/worktrees/"* ]]; then
    cat << EOF
{"error":"BLOCKED: ALL repository work MUST be performed in a git worktree, not the main repository.\\n\\n**MANDATORY WORKFLOW:**\\n1. Create worktree from origin/main\\n2. Make changes in worktree\\n3. Create PR for review\\n4. Merge PR after approval\\n\\n**To create a worktree:**\\n  cd ${WORKTREE_WORKSPACE_ROOT}/${REPO_NAME}\\n  git fetch origin main\\n  git worktree add -b <issue>/<description> ../worktrees/${REPO_NAME}-<issue> origin/main\\n  cd ../worktrees/${REPO_NAME}-<issue>\\n\\n**Why?** This ensures:\\n- All changes start from the latest main branch\\n- All changes go through PR review\\n- No regressions from outdated code\\n- Clean git history with squash merges"}
EOF
    exit 1
fi

# All checks passed - allow the operation
echo '{"continue":true}'

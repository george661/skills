#!/bin/bash
#
# enforce-skill-project-root.sh - Ensures skill invocations run from $PROJECT_ROOT
#
# Skills load credentials from $PROJECT_ROOT/.env (falling back to process.cwd()).
# When agents work in worktrees or subdirectories, cwd may not contain .env,
# causing credential resolution failures. This hook detects skill invocations
# via Bash and blocks them if cwd is not PROJECT_ROOT.
#
# Matches Bash commands containing:
#   npx tsx .claude/skills/...
#   npx tsx ~/.claude/skills/...
#   npx tsx $HOME/.claude/skills/...
#
# Configuration:
#   PROJECT_ROOT - Expected project root (auto-detected from TENANT_WORKSPACE_ROOT or ~/projects)
#

set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# No command - allow
if [[ -z "$COMMAND" ]]; then
    echo '{"continue":true}'
    exit 0
fi

# Check if the command invokes a skill
# Match patterns:
#   npx tsx .claude/skills/
#   npx tsx ~/.claude/skills/
#   npx tsx /Users/.../.claude/skills/
#   npx tsx $HOME/.claude/skills/
IS_SKILL=false
if echo "$COMMAND" | grep -qE 'npx\s+tsx\s+.*\.claude/skills/'; then
    IS_SKILL=true
fi

# Not a skill invocation - allow
if [[ "$IS_SKILL" != "true" ]]; then
    echo '{"continue":true}'
    exit 0
fi

# Determine the expected PROJECT_ROOT
# Priority: $PROJECT_ROOT env var > detect from git toplevel > workspace default
if [[ -n "${PROJECT_ROOT:-}" ]]; then
    EXPECTED_ROOT="$PROJECT_ROOT"
else
    # Try to detect from git - walk up from cwd to find the workspace root
    # In a worktree, git rev-parse --show-toplevel gives the worktree root (wrong).
    # We need the actual project root where .env lives.
    # Use TENANT_WORKSPACE_ROOT if set, otherwise ~/projects
    WORKSPACE="${TENANT_WORKSPACE_ROOT:-$HOME/projects}"

    # Try to figure out which project we're in by examining the path
    CURRENT_DIR="$(pwd)"
    if [[ "$CURRENT_DIR" == "$WORKSPACE"/* ]]; then
        # We're somewhere under the workspace. The project root is the
        # first directory level under workspace.
        # e.g., ~/projects/myproject/api-service/... -> ~/projects/myproject
        # But if we're in a worktree like ~/projects/myproject/worktrees/api-service/PROJ-123-fix/...
        # we still want ~/projects/myproject
        REL="${CURRENT_DIR#$WORKSPACE/}"
        PROJECT_DIR="${REL%%/*}"
        EXPECTED_ROOT="$WORKSPACE/$PROJECT_DIR"
    else
        # Not under workspace - use cwd (can't enforce)
        echo '{"continue":true}'
        exit 0
    fi
fi

# Resolve to absolute path
EXPECTED_ROOT=$(cd "$EXPECTED_ROOT" 2>/dev/null && pwd || echo "$EXPECTED_ROOT")

# Get current working directory (absolute)
CWD="$(pwd)"

# Check if we're already at PROJECT_ROOT
if [[ "$CWD" == "$EXPECTED_ROOT" ]]; then
    echo '{"continue":true}'
    exit 0
fi

# Check if .env exists at PROJECT_ROOT (if it doesn't, there's nothing to enforce)
if [[ ! -f "$EXPECTED_ROOT/.env" ]]; then
    echo '{"continue":true}'
    exit 0
fi

# Extract the skill name for the error message
SKILL_NAME=$(echo "$COMMAND" | grep -oE '\.claude/skills/[^ ]+' | head -1 || echo "unknown")

# Block the command - agent must run skills from PROJECT_ROOT
cat << EOF
{"error":"BLOCKED: Skill invocation must run from PROJECT_ROOT.\\n\\nSkill: ${SKILL_NAME}\\nCurrent directory: ${CWD}\\nExpected directory: ${EXPECTED_ROOT}\\n\\nSkills load credentials from \$PROJECT_ROOT/.env. Running from a worktree or subdirectory causes credential resolution to fail because the .env file is not present there.\\n\\n**To fix - use one of these approaches:**\\n\\n1. Prefix the command with cd:\\n   cd ${EXPECTED_ROOT} && ${COMMAND}\\n\\n2. Set PROJECT_ROOT explicitly:\\n   PROJECT_ROOT=${EXPECTED_ROOT} ${COMMAND}\\n\\n3. Run the command from PROJECT_ROOT directly."}
EOF
exit 1

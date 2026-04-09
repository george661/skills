#!/usr/bin/env bash
# migrate-commands.sh — Task 7: Migrate commands from hardcoded providers to router layers
#
# Phase 1: jira/ -> issues/ for the 8 core issue-tracker skills
# Phase 2: fly/concourse -> ci/ for build-related skills (with renames)
#
# Does NOT migrate Jira-only skills (worklog_identity, add_issue_link, move_to_board,
# add_attachment, jira_blockers) or Concourse-specific ops (validate_pipeline, set_pipeline, etc.)

set -euo pipefail

COMMANDS_DIR="$(cd "$(dirname "$0")/../commands" && pwd)"
CHANGED_FILES=()
TOTAL_REPLACEMENTS=0

echo "=== Phase 1: jira/ -> issues/ (8 router-backed skills) ==="
echo ""

# The 8 issue tracker skills that have router equivalents
ISSUE_SKILLS=(
  get_issue
  search_issues
  create_issue
  update_issue
  transition_issue
  add_comment
  list_comments
  list_transitions
)

for skill in "${ISSUE_SKILLS[@]}"; do
  # Pattern 1: ~/.claude/skills/jira/<skill> -> ~/.claude/skills/issues/<skill>
  count=$(grep -rl "skills/jira/${skill}" "$COMMANDS_DIR" 2>/dev/null | wc -l | tr -d ' ')
  if [ "$count" -gt 0 ]; then
    files=$(grep -rl "skills/jira/${skill}" "$COMMANDS_DIR")
    echo "  jira/${skill} -> issues/${skill}  ($count files)"
    while IFS= read -r f; do
      # Use sed to replace both ~/.claude/skills/jira/ and .claude/skills/jira/ patterns
      sed -i '' "s|skills/jira/${skill}|skills/issues/${skill}|g" "$f"
      CHANGED_FILES+=("$f")
    done <<< "$files"
    TOTAL_REPLACEMENTS=$((TOTAL_REPLACEMENTS + count))
  fi
done

echo ""
echo "=== Phase 2: fly/concourse -> ci/ (build-related skills) ==="
echo ""

# fly/list_builds -> ci/list_builds (same name)
count=$(grep -rl "skills/fly/list_builds" "$COMMANDS_DIR" 2>/dev/null | wc -l | tr -d ' ')
if [ "$count" -gt 0 ]; then
  files=$(grep -rl "skills/fly/list_builds" "$COMMANDS_DIR")
  echo "  fly/list_builds -> ci/list_builds  ($count files)"
  while IFS= read -r f; do
    sed -i '' 's|skills/fly/list_builds|skills/ci/list_builds|g' "$f"
    CHANGED_FILES+=("$f")
  done <<< "$files"
  TOTAL_REPLACEMENTS=$((TOTAL_REPLACEMENTS + count))
fi

# fly/trigger_job -> ci/trigger_build (renamed)
count=$(grep -rl "skills/fly/trigger_job" "$COMMANDS_DIR" 2>/dev/null | wc -l | tr -d ' ')
if [ "$count" -gt 0 ]; then
  files=$(grep -rl "skills/fly/trigger_job" "$COMMANDS_DIR")
  echo "  fly/trigger_job -> ci/trigger_build  ($count files)"
  while IFS= read -r f; do
    sed -i '' 's|skills/fly/trigger_job|skills/ci/trigger_build|g' "$f"
    CHANGED_FILES+=("$f")
  done <<< "$files"
  TOTAL_REPLACEMENTS=$((TOTAL_REPLACEMENTS + count))
fi

# fly/watch_build -> ci/get_build_logs (renamed)
count=$(grep -rl "skills/fly/watch_build" "$COMMANDS_DIR" 2>/dev/null | wc -l | tr -d ' ')
if [ "$count" -gt 0 ]; then
  files=$(grep -rl "skills/fly/watch_build" "$COMMANDS_DIR")
  echo "  fly/watch_build -> ci/get_build_logs  ($count files)"
  while IFS= read -r f; do
    sed -i '' 's|skills/fly/watch_build|skills/ci/get_build_logs|g' "$f"
    CHANGED_FILES+=("$f")
  done <<< "$files"
  TOTAL_REPLACEMENTS=$((TOTAL_REPLACEMENTS + count))
fi

# concourse/get_build -> ci/get_build_status (renamed)
count=$(grep -rl "skills/concourse/get_build" "$COMMANDS_DIR" 2>/dev/null | wc -l | tr -d ' ')
if [ "$count" -gt 0 ]; then
  files=$(grep -rl "skills/concourse/get_build" "$COMMANDS_DIR")
  echo "  concourse/get_build -> ci/get_build_status  ($count files)"
  while IFS= read -r f; do
    sed -i '' 's|skills/concourse/get_build|skills/ci/get_build_status|g' "$f"
    CHANGED_FILES+=("$f")
  done <<< "$files"
  TOTAL_REPLACEMENTS=$((TOTAL_REPLACEMENTS + count))
fi

# concourse/list_builds -> ci/list_builds (same name)
count=$(grep -rl "skills/concourse/list_builds" "$COMMANDS_DIR" 2>/dev/null | wc -l | tr -d ' ')
if [ "$count" -gt 0 ]; then
  files=$(grep -rl "skills/concourse/list_builds" "$COMMANDS_DIR")
  echo "  concourse/list_builds -> ci/list_builds  ($count files)"
  while IFS= read -r f; do
    sed -i '' 's|skills/concourse/list_builds|skills/ci/list_builds|g' "$f"
    CHANGED_FILES+=("$f")
  done <<< "$files"
  TOTAL_REPLACEMENTS=$((TOTAL_REPLACEMENTS + count))
fi

# concourse/pipeline_health -> ci/get_build_status (renamed)
count=$(grep -rl "skills/concourse/pipeline_health" "$COMMANDS_DIR" 2>/dev/null | wc -l | tr -d ' ')
if [ "$count" -gt 0 ]; then
  files=$(grep -rl "skills/concourse/pipeline_health" "$COMMANDS_DIR")
  echo "  concourse/pipeline_health -> ci/get_build_status  ($count files)"
  while IFS= read -r f; do
    sed -i '' 's|skills/concourse/pipeline_health|skills/ci/get_build_status|g' "$f"
    CHANGED_FILES+=("$f")
  done <<< "$files"
  TOTAL_REPLACEMENTS=$((TOTAL_REPLACEMENTS + count))
fi

echo ""
echo "=== Summary ==="
# Deduplicate changed files
UNIQUE_FILES=($(printf '%s\n' "${CHANGED_FILES[@]}" | sort -u))
echo "Total file-level replacements: $TOTAL_REPLACEMENTS"
echo "Unique files modified: ${#UNIQUE_FILES[@]}"
echo ""
echo "Modified files:"
for f in "${UNIQUE_FILES[@]}"; do
  echo "  $(basename "$f")"
done

echo ""
echo "=== Verification: remaining jira/ references for migrated skills ==="
REMAINING=0
for skill in "${ISSUE_SKILLS[@]}"; do
  found=$(grep -rl "skills/jira/${skill}" "$COMMANDS_DIR" 2>/dev/null | wc -l | tr -d ' ' || true)
  if [ "$found" -gt 0 ]; then
    echo "  WARNING: $found files still reference skills/jira/${skill}"
    REMAINING=$((REMAINING + found))
  fi
done
if [ "$REMAINING" -eq 0 ]; then
  echo "  (none — all migrated)"
fi

echo ""
echo "=== Verification: remaining fly/concourse references for migrated skills ==="
REMAINING_CI=0
for pattern in "skills/fly/list_builds" "skills/fly/trigger_job" "skills/fly/watch_build" \
               "skills/concourse/get_build" "skills/concourse/list_builds" "skills/concourse/pipeline_health"; do
  found=$(grep -rl "$pattern" "$COMMANDS_DIR" 2>/dev/null | wc -l | tr -d ' ' || true)
  if [ "$found" -gt 0 ]; then
    echo "  WARNING: $found files still reference $pattern"
    REMAINING_CI=$((REMAINING_CI + found))
  fi
done
if [ "$REMAINING_CI" -eq 0 ]; then
  echo "  (none — all migrated)"
fi

echo ""
echo "=== NOT migrated (Jira-specific, no router equivalent) ==="
for pattern in "skills/jira/worklog_identity" "skills/jira/add_issue_link" "skills/jira/move_to_board" \
               "skills/jira/add_attachment" "skills/jira/jira_blockers"; do
  found=$(grep -rl "$pattern" "$COMMANDS_DIR" 2>/dev/null | wc -l | tr -d ' ' || true)
  if [ "$found" -gt 0 ]; then
    echo "  $pattern  ($found files — intentionally kept)"
  fi
done

echo ""
echo "=== NOT migrated (Concourse-specific ops) ==="
for pattern in "skills/fly/validate_pipeline" "skills/fly/set_pipeline" "skills/fly/login" \
               "skills/fly/abort_build" "skills/fly/containers" "skills/fly/land_worker" \
               "skills/fly/prune_worker" "skills/fly/workers" "skills/fly/wait-for-ci" \
               "skills/concourse/list_pipelines" "skills/concourse/get_pipeline" \
               "skills/concourse/get_pipeline_config" "skills/concourse/list_jobs" \
               "skills/concourse/list_resources" "skills/concourse/pause_pipeline" \
               "skills/concourse/unpause_pipeline" "skills/concourse/set_pipeline"; do
  found=$(grep -rl "$pattern" "$COMMANDS_DIR" 2>/dev/null | wc -l | tr -d ' ' || true)
  if [ "$found" -gt 0 ]; then
    echo "  $pattern  ($found files — intentionally kept)"
  fi
done

echo ""
echo "Done."

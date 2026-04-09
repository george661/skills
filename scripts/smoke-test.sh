#!/usr/bin/env bash
set -euo pipefail

PASS=0
FAIL=0
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

report() {
  local status="$1" name="$2"
  if [ "$status" -eq 0 ]; then
    echo "  PASS  $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $name"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== skills smoke test ==="
echo ""

# 1. Source .env if present
[ -f "$PROJECT_ROOT/.env" ] && set -a && source "$PROJECT_ROOT/.env" && set +a

# 2. Config validator runs without crashing
echo "--- Config validator ---"
python3 "$PROJECT_ROOT/hooks/validate-config.py" >/dev/null 2>&1
report $? "validate-config.py exits cleanly"

# 3. Issue router — jira provider (expect graceful error, not crash)
echo "--- Issue router (jira) ---"
out=$(ISSUE_TRACKER=jira npx tsx "$PROJECT_ROOT/skills/issues/get_issue.ts" \
  '{"issue_key":"TEST-1"}' 2>&1 || true)
echo "$out" | grep -qiE "error|unauthorized|missing|not found"
report $? "jira get_issue graceful error"

# 4. Issue router — github provider (expect graceful error, not crash)
echo "--- Issue router (github) ---"
out=$(ISSUE_TRACKER=github npx tsx "$PROJECT_ROOT/skills/issues/get_issue.ts" \
  '{"issue_key":"test-org/test-repo#1"}' 2>&1 || true)
echo "$out" | grep -qiE "error|unauthorized|missing|not found"
report $? "github get_issue graceful error"

# 5. CI router — github_actions (expect graceful error, not crash)
echo "--- CI router (github_actions) ---"
out=$(CI_PROVIDER=github_actions npx tsx "$PROJECT_ROOT/skills/ci/get_build_status.ts" \
  '{"repo":"test","run_id":1}' 2>&1 || true)
echo "$out" | grep -qiE "error|unauthorized|missing|not found"
report $? "github_actions get_build_status graceful error"

# 6. Summary
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1

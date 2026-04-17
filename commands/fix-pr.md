<!-- MODEL_TIER: sonnet -->
<!-- DISPATCH: Spawn a Task subagent with model: "sonnet" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Sonnet. -->

---
description: Triggered by failed PR build OR unresolved review comments - fix issues, push, then exit
arguments:
  - name: issue
    description: Jira issue key (e.g., PROJ-123)
    required: true
  - name: repo
    description: Repository slug (e.g., test-data). If omitted, resolved from checkpoint or Jira labels.
    required: false
  - name: pr_number
    description: Pull request number. If omitted, resolved from checkpoint or Jira labels.
    required: false
  - name: unresolved
    description: "Specific unresolved comments from the orchestrator (e.g., 'WARNING: naive CSV parser at line 373'). When provided, fix ONLY these items — do not re-discover from scratch."
    required: false
---

# Fix PR: $ARGUMENTS.issue

## MANDATORY: Worktree + PR Workflow

> **⛔ CRITICAL REQUIREMENTS:**
>
> 1. **MUST work in the existing worktree** - All fixes must be made in the worktree created by `/create-implementation-plan`
> 2. **NEVER create a new branch/PR** - Fix on the same branch, push to same PR
> 3. **The `enforce-worktree.sh` hook will BLOCK** any attempt to modify files outside a worktree
>
> **This command assumes the worktree already exists from `/create-implementation-plan`.**

---

## Purpose

This command handles CI pipeline failures AND PR review comments:
- Load PR and worktree info from memory
- **Navigate to existing worktree** (created by /create-implementation-plan)
- Get pipeline failure logs (if CI failed)
- Check for unresolved PR review comments
- Analyze and fix issues (CI failures and/or review feedback)
- Run local validation again
- Push fix to the same branch (**same PR**)

**Trigger:** CI pipeline failed OR unresolved PR review comments exist for $ARGUMENTS.issue
**Next step after this command:** Wait for CI to re-run, then run `/fix-pr` again if failed or `/resolve-pr` if passed.

---

## Step Label (MANDATORY)

At the START of this command, update the step label to `step:fixing-pr`:

```bash
issue=$(npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "labels"}')
labels=$(echo "$issue" | jq -r '.fields.labels // [] | map(select(startswith("step:") | not)) + ["step:fixing-pr"] | @json')
npx tsx ~/.claude/skills/issues/update_issue.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"labels\": $labels, \"notify_users\": false}"
```

---

## Comment Severity and Required Actions

| Severity | Action Required |
|----------|-----------------|
| 🔴 Critical | MUST fix - merge blocked |
| 🟠 Warning | MUST fix or justify - merge blocked |
| 🟡 Suggestion | Fix or acknowledge with reason |
| 🟢 Nitpick | Fix or acknowledge |
| ❓ Question | MUST respond - merge blocked |

**Repeat this command until ALL critical/warning comments are addressed and CI passes.**

---

## Skill Reference (MANDATORY — use these exact calls)

**DO NOT use MCP tools (mcp__bitbucket__*, mcp__jira__*). Use the Bash skill calls below instead.**

### IMPORTANT: Always run skills from the platform root directory
```bash
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/...
```
Running from inside a worktree's Go module directory will cause `ERR_MODULE_NOT_FOUND`.

### VCS Skills (auto-routes to Bitbucket or GitHub)

```bash
# Get PR details (status, author, branch info)
npx tsx ~/.claude/skills/vcs/get_pull_request.ts '{"repo": "<repo>", "pr_number": <num>}'

# Get PR diff (returns plain text)
npx tsx ~/.claude/skills/vcs/get_pull_request_diff.ts '{"repo": "<repo>", "pr_number": <num>}'

# List ALL PR comments (review comments you must address)
npx tsx ~/.claude/skills/vcs/list_pull_request_comments.ts '{"repo": "<repo>", "pr_number": <num>}'

# Reply to a PR comment (confirming fix or responding to question)
npx tsx ~/.claude/skills/vcs/add_pull_request_comment.ts '{"repo": "<repo>", "pr_number": <num>, "comment_text": "<text>", "parent_id": <comment_id>}'

# Add inline comment on specific file/line
npx tsx ~/.claude/skills/vcs/add_pull_request_comment.ts '{"repo": "<repo>", "pr_number": <num>, "comment_text": "<text>", "path": "<file>", "line": <num>}'
```

### Jira Skills

```bash
# Get issue (note: parameter is issue_key, NOT issueKey)
npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "<KEY>", "fields": "summary,status,labels"}'

# Update issue labels
npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "<KEY>", "labels": ["label1"], "notify_users": false}'
```

### CI Skills (Concourse via fly)

```bash
# Wait for CI to complete — returns structured per-task output
# (CI monitoring is done by the /work orchestrator, not /fix-pr directly)
npx tsx ~/.claude/skills/ci/wait_for_ci.ts '{"repo": "<repo>", "job": "pr-check", "timeout_seconds": 900}'

# Extract failing tasks from the result
echo "$ci_result" | jq -r '.output | to_entries[] | select(.value.success == false) | "FAILED: \(.key)\n\(.value.logs[-5:] | join("\n"))"'
```

### JSON Escaping
When posting comments with code blocks, use a heredoc pattern or write to a temp file to avoid shell escaping issues with backticks and special characters.

---

## Pre-Push Guardrails (MANDATORY)

Before pushing any fix, verify:
```bash
# 1. Never commit node_modules
if git ls-files --cached | grep -q '^node_modules/'; then
  git rm -r --cached node_modules/
fi

# 2. Ensure .gitignore exists
if [ ! -f .gitignore ]; then
  echo -e "node_modules/\ndist/\n.env\n*.log\ncoverage/" > .gitignore
  git add .gitignore
fi

# 3. Check staged files for accidents
git diff --cached --name-only | grep -E '^(node_modules/|\.env$|dist/)' && echo "ERROR: forbidden files staged" && exit 1

# 4. NEVER commit plan files (they belong in Jira + agentdb, not the repo)
git rm -f implementation-plan.md IMPLEMENTATION_PLAN.md 2>/dev/null || true
git diff --cached --name-only | grep -iE '^(implementation.plan|IMPLEMENTATION.PLAN)' && echo "ERROR: plan files must not be committed" && exit 1

# 5. Block unexpected .md files in repo root
git diff --cached --name-only | grep -E '^[^/]+\.md$' | grep -v -E '^(README|CLAUDE|TESTING|CHANGELOG|CONTRIBUTING|LICENSE)\.md$' && echo "ERROR: unexpected .md file in repo root" && exit 1

# 6. Run language-specific lint/vet BEFORE pushing (catches unused imports, type errors, etc.)
# Detect language from file extensions and run the appropriate checker:
changed=$(git diff --cached --name-only)
if echo "$changed" | grep -q '\.go$'; then
  # Go: run go vet (with integration build tag if integration test files changed)
  vet_tags=""
  if echo "$changed" | grep -q 'integration'; then
    vet_tags="-tags integration"
  fi
  (cd "$(dirname "$(echo "$changed" | grep '\.go$' | head -1)")" && go vet $vet_tags ./...) || { echo "ERROR: go vet failed — fix before pushing"; exit 1; }
elif echo "$changed" | grep -q '\.ts$\|\.tsx$'; then
  # TypeScript: run tsc --noEmit if tsconfig exists
  if [ -f tsconfig.json ]; then
    npx tsc --noEmit || { echo "ERROR: TypeScript type check failed"; exit 1; }
  fi
fi
```

---

```bash
npx tsx ~/.claude/skills/jira/worklog_identity.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"phase\": \"starting\", \"command\": \"/fix-pr\", \"message\": \"Applying fixes to PR\"}" 2>/dev/null || true
```

## Phase 0: Resolve Repo and PR Number (MANDATORY)

You MUST know the repo slug and PR number before proceeding. Resolve them in this order:

1. **From arguments** — if `$ARGUMENTS.repo` and `$ARGUMENTS.pr_number` are provided, use them directly.
2. **From checkpoint** — if not provided as arguments:
   ```bash
   checkpoint=$(python3 ~/.claude/hooks/checkpoint.py load $ARGUMENTS.issue 2>/dev/null || echo '{"found":false}')
   repo=$(echo "$checkpoint" | jq -r '.checkpoint.data.repo // empty')
   pr_number=$(echo "$checkpoint" | jq -r '.checkpoint.data.pr_number // empty')
   ```
3. **From Jira labels** — if checkpoint has no PR info:
   ```bash
   issue=$(npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "labels"}')
   # Look for label matching "pr:<repo>/<number>"
   pr_label=$(echo "$issue" | jq -r '.fields.labels[]? | select(startswith("pr:"))' | head -1)
   repo=$(echo "$pr_label" | sed 's|pr:||; s|/.*||')
   pr_number=$(echo "$pr_label" | sed 's|.*/||')
   ```

**If repo or pr_number is still empty after all 3 steps, STOP and report the error.** Do NOT guess or brute-force search for the PR.

Print: `[phase 0] Repo: <repo>, PR: #<pr_number>`

---

## Orchestrator-Supplied Unresolved Comments

If `$ARGUMENTS.unresolved` is provided, it contains the specific review comments that are STILL
unresolved after a previous fix-pr cycle. **When present:**

1. **Fix ONLY these items** — do not re-discover from scratch by listing all PR comments
2. **Each item includes severity, description, file, and line** — go directly to the code and fix it
3. **Still run the full verification phase** (Phase 10) to confirm all comments are addressed

This avoids the failure mode where the local model re-lists comments, finds already-fixed ones,
and declares victory without addressing the remaining issues.

---

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

1. Load PR and worktree info (use repo and PR from Phase 0)
2. Parse TESTING.md for repo-specific validation commands
3. Check pipeline status and get failure logs if failed
4. **Enumerate ALL unresolved issues into a checklist BEFORE making any code changes:**
   - If `$ARGUMENTS.unresolved` is provided, use those items directly
   - Otherwise, fetch ALL PR review comments using `list_pull_request_comments`
   - **Create a TODO item for EACH critical/warning comment** with its comment ID, severity, file, and line
   - Print the full checklist: `"Fixing N issues: [1] CRITICAL file:line — description, [2] WARNING file:line — description, ..."`
   - **After fixing each item, verify it by grepping the changed code** for the specific pattern the comment flagged
   - Do NOT declare done until every TODO is checked off
5. Analyze failures and/or review feedback — read each comment carefully
6. Fix CI issues (if any)
7. Address PR review comments (if any) — **reply to EACH comment** confirming the fix using `add_pull_request_comment` with `parent_id`
8. ⛔ MANDATORY: Run scope-appropriate validation (see Validation Tiers below)
9. ⛔ MANDATORY: Run pre-push guardrails (no node_modules, .gitignore exists)
9.5. Sync branch with main before pushing fixes:
   ```bash
   cd <worktree-path>
   git fetch origin main
   behind=$(git rev-list --count HEAD..origin/main)
   if [ "$behind" -gt 0 ]; then
     echo "[branch-sync] Branch is $behind commit(s) behind main — merging"
     git merge origin/main --no-edit
     if [ $? -ne 0 ]; then
       echo "[branch-sync] CONFLICT — resolve conflicts, commit, then continue"
       exit 1
     fi
     echo "[branch-sync] Merged $behind commit(s) from main"
   else
     echo "[branch-sync] Branch is up to date with main"
   fi
   ```
10. Push fix to same branch — use `git push` (do NOT use `--set-upstream` if branch already tracks remote)
11. ⛔ MANDATORY: Run completion verification (see Completion Verification below)

---

## Validation Tiers (Phase 8)

**Classify your fix BEFORE choosing validation.** Use the MINIMUM tier that covers your changes.

### Tier 1: Config-only (< 2 minutes)
**When:** Only `.gitignore`, `README.md`, `.agent-context.json`, `package.json` (non-dependency fields), CI config, or other non-code files changed.
```bash
npx tsc --noEmit   # typecheck still compiles all code — catches import issues
```
No test run needed. Config files don't affect test outcomes.

### Tier 2: Code change, no test changes (< 5 minutes)
**When:** Source code changed (`.ts`, `.tsx`, `.go`, etc.) but no tests were added/modified/removed.
```bash
npx tsc --noEmit
npm run lint        # if available
# Run ONLY tests for files you changed:
npx playwright test <changed-spec-files> --project=chromium
# OR for Go: go test ./path/to/changed/package/...
```

### Tier 3: Code + test changes (full suite)
**When:** You modified or removed code AND changed corresponding tests, OR the CI failure was a test failure.
```bash
npx tsc --noEmit
npm run lint
npm test            # full test suite
```
If you removed or renamed code, the corresponding tests WILL break — find and update them.

### How to classify
```bash
# List changed files to determine tier
git diff --name-only HEAD~1
# Config-only? → Tier 1
# .ts/.go changes but no test files? → Tier 2
# Test files changed or CI test failure? → Tier 3
```

**DO NOT run `npm run test:journeys` or the full E2E suite for Tier 1 or Tier 2 fixes.** E2E tests against a live environment take 20+ minutes and are not proportionate to small fixes.

### Authenticated API Testing (MANDATORY for API_ENDPOINT issues)

When fixing API endpoint issues, you MUST test with **authenticated** requests. Testing
unauthenticated (getting 401) proves nothing — 401 is always the expected unauthenticated
behavior. A previous PROJ-2100 validation declared PASS based on 401 responses, then had to
be reopened when authenticated testing revealed a 403 bug.

**Search AgentDB first** for the latest procedure:
```bash
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/agentdb/pattern_search.ts '{"task": "authenticated API testing"}'
```

**Quick reference** (if AgentDB pattern unavailable):
```bash
# 1. Get test credentials (from e2e-tests)
cd $PROJECT_ROOT/e2e-tests && npm install --silent 2>/dev/null && npm run test-data:download
ORG_ADMIN=$(node -e "const d=JSON.parse(require('fs').readFileSync('tests/fixtures/testData.json'));const u=(Array.isArray(d)?d:d.users).find(u=>u.role==='org_admin');console.log(JSON.stringify(u))")
EMAIL=$(echo "$ORG_ADMIN" | jq -r .email)
PASSWORD=$(echo "$ORG_ADMIN" | jq -r .password)
ORG_ID=$(echo "$ORG_ADMIN" | jq -r .orgId)

# 2. Authenticate via Cognito (e2e-test-headless client requires SECRET_HASH)
POOL_ID="us-east-1_yMqRDIh9x"
CLIENT_ID="7979i07oaa25vqc95eke44bfee"
CLIENT_SECRET=$(aws cognito-idp describe-user-pool-client --user-pool-id "$POOL_ID" --client-id "$CLIENT_ID" --profile ${AWS_PROFILE_DEV} --region us-east-1 --query 'UserPoolClient.ClientSecret' --output text)
SECRET_HASH=$(echo -n "${EMAIL}${CLIENT_ID}" | openssl dgst -sha256 -hmac "$CLIENT_SECRET" -binary | base64)
TOKEN=$(aws cognito-idp admin-initiate-auth --user-pool-id "$POOL_ID" --client-id "$CLIENT_ID" --auth-flow ADMIN_USER_PASSWORD_AUTH --auth-parameters USERNAME="$EMAIL",PASSWORD="$PASSWORD",SECRET_HASH="$SECRET_HASH" --profile ${AWS_PROFILE_DEV} --region us-east-1 | jq -r '.AuthenticationResult.IdToken')

# 3. Test with auth — expect 200, NOT 401
curl -s -w '\nHTTP %{http_code}' \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  "https://api.dev.example.com/<path>"
```

**CRITICAL:** A 401 on an unauthenticated request does NOT prove a bug is fixed.
You must see 200/201 with valid response data on an authenticated request.

---

## Update Workflow Step

After pushing fixes, update the workflow context in memory:

```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts "{\"session_id\": \"${TENANT_NAMESPACE}\", \"task\": \"active-workflow-$ARGUMENTS.issue\", \"input\": {\"issue_key\": \"$ARGUMENTS.issue\", \"step\": \"fixing-pr\", \"last_updated\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}, \"output\": \"Fixes pushed\", \"reward\": 0.5, \"success\": false, \"critique\": \"PR fixes applied\"}"
```

## MANDATORY: Structured Fix Output

After pushing fixes, print a machine-parseable fix manifest so the orchestrator can
diff-verify each claim against the actual PR diff:

```
## FIX_MANIFEST
| Comment ID | Severity | Fix Applied | File | Lines Changed |
|------------|----------|-------------|------|---------------|
| 769235514 | CRITICAL | Removed implementation-plan.md from repo | implementation-plan.md | deleted |
| 769235524 | WARNING | Replaced getCodeStatusAtIndex with findCodeByEmail | tests/journeys/referral-codes.spec.ts | 390-392 |
```

This allows the orchestrator to verify each fix by checking the diff for changes at the
specified file and line range. Do NOT omit this output or replace it with prose descriptions.

---

## Completion Verification (Phase 11 — MANDATORY)

After pushing fixes, verify ALL review comments are addressed before declaring done.
**Do NOT skip this phase.** Previous failures were caused by declaring victory after
fixing some but not all comments.

```bash
# 1. List all inline review comments
comments=$(npx tsx ~/.claude/skills/vcs/list_pull_request_comments.ts '{"repo": "<repo>", "pr_number": <num>}')

# 2. Extract CRITICAL and WARNING comments
critical_warnings=$(echo "$comments" | jq '[.values[] | select(.inline) | select(.content.raw | test("\\[CRITICAL\\]|\\[WARNING\\]"; "i")) | {id: .id, severity: (.content.raw | split("]")[0] | ltrimstr("[")), path: .inline.path, line: .inline.to, snippet: (.content.raw | split("\n")[0][:100])}]')

# 3. For each CRITICAL/WARNING comment, check if the referenced code has changed
diff=$(npx tsx ~/.claude/skills/vcs/get_pull_request_diff.ts '{"repo": "<repo>", "pr_number": <num>}')

# 4. Print verification result
echo "$critical_warnings" | jq -r '.[] | "Checking \(.severity) at \(.path):\(.line) — \(.snippet)"'
```

**For each comment:**
- Read the actual file at the referenced line
- Verify the issue described in the comment is no longer present
- If ANY CRITICAL or WARNING issue persists, DO NOT declare done — fix it first

**Only after ALL issues verified as resolved**, print the FIX_MANIFEST and declare complete.

---

**START NOW: Begin Phase 0/Step 0.**

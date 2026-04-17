<!-- MODEL_TIER: sonnet -->
<!-- DISPATCH: Spawn a Task subagent with model: "sonnet" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Sonnet. -->

<!-- Integration: ISSUE_TRACKER=jira, VCS_PROVIDER=auto (bitbucket|github via vcs-router) -->
---
description: Implement the work in the implementation plan, run local validation, create PR, then exit
arguments:
  - name: issue
    description: Jira issue key (e.g., ${TENANT_PROJECT}-123)
    required: true
---

# Implement: $ARGUMENTS.issue

## MANDATORY: Worktree + PR Workflow

> **⛔ CRITICAL REQUIREMENTS:**
>
> 1. **MUST be in a worktree** - The `enforce-worktree.sh` hook will BLOCK all file modifications unless you are in a worktree based on `origin/main`
> 2. **MUST create a PR** - NO direct pushes to main are allowed. All changes must go through PR review.
>
> **Workflow enforced by this command:**
> - Work in worktree → Local validation → Create PR → Wait for CI → Review → Merge
>
> **If not in a worktree:** Run `/create-implementation-plan $ARGUMENTS.issue` first. That command creates the worktree.

---

## Tool Usage Reference

> See `.claude/skills/examples/{tool}-mcp.md` for optimized tool patterns
> See `.claude/skills/checkpointing.md` for resumable workflow patterns
> See `.claude/skills/vcs/provider.skill.md` for VCS abstraction (Bitbucket/GitHub)

---

## Resume Check

Check for existing checkpoint before starting:

```bash
checkpoint=$(python3 ~/.claude/hooks/checkpoint.py load $ARGUMENTS.issue 2>/dev/null || echo '{"found":false}')
# If found, can resume from: tdd, local-validation, pr-creation
```

---

## Purpose

This command handles the implementation and PR creation phase:
- Load implementation plan from memory (includes worktree path)
- **Verify you are in the correct worktree** (based on origin/main)
- **Update step label to `step:implementing`**
- TDD implementation (RED-GREEN-REFACTOR-COMMIT)
- Run all local validation (lint, typecheck, tests, manual testing)
- **MANDATORY: Create PR** and link to Jira
- **Update step label to `step:awaiting-ci` after PR creation**

**Prerequisite:** `/create-implementation-plan $ARGUMENTS.issue` must have been run first (creates worktree).
**Next step after this command:** Wait for CI pipeline, then run `/fix-pr` if failed or `/resolve-pr` if passed.

> **CI Infrastructure:** CI is monitored by the `/work` orchestrator via `~/.claude/skills/ci/wait_for_ci.ts`, which routes through the unified CI router and returns structured per-task output for all supported CI providers.

---

## Step Labels (MANDATORY)

At the START of this command, update the step label:

```bash
issue=$(npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "labels"}')
labels=$(echo "$issue" | jq -r '.fields.labels // [] | map(select(startswith("step:") | not)) + ["step:implementing"] | @json')
npx tsx ~/.claude/skills/issues/update_issue.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"labels\": $labels, \"notify_users\": false}"
```

After PR creation, update to `step:awaiting-ci`.

---

## Skill Reference (MANDATORY — use these exact calls)

**DO NOT use MCP tools (mcp__bitbucket__*, mcp__jira__*). Use the Bash skill calls below instead.**

### IMPORTANT: Always run skills from the platform root directory
```bash
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/...
```
Running from inside a worktree's Go module directory will cause `ERR_MODULE_NOT_FOUND`.

### Jira Skills

```bash
# Get issue (note: parameter is issue_key, NOT issueKey)
npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "<KEY>", "fields": "summary,status,labels"}'

# Update issue labels
npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "<KEY>", "labels": ["label1"], "notify_users": false}'

# Add comment to issue
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "<KEY>", "body": "<markdown>"}'
```

### VCS Skills (auto-routes to Bitbucket or GitHub)

```bash
# Create PR (unified interface — provider auto-detected from repo name)
npx tsx ~/.claude/skills/vcs/create_pull_request.ts '{"repo": "<repo>", "title": "<title>", "source_branch": "<branch>", "description": "<desc>"}'
```

### JSON Escaping
When posting comments with code blocks, use a heredoc pattern or write to a temp file to avoid shell escaping issues with backticks and special characters.

---

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

1. Load implementation plan from AgentDB (MANDATORY — use exact key below)
2. ⛔ **Plan freshness check** — verify worktree plan matches latest Jira plan
3. Parse TESTING.md for repo-specific validation commands
4. TDD implementation (RED-GREEN-REFACTOR-COMMIT)
5. ⛔ MANDATORY: Run all pre-commit validation steps
6. LOCAL VALIDATION - manual testing per issue type
6.5. ⛔ **File-location guardrail** — verify no files were created/modified outside the plan
6.6. ⛔ **Plan compliance check** — verify implementation doesn't contradict plan constraints
7. ⛔ MANDATORY: Verify all files are staged before pushing (check .gitignore, NO node_modules)
8. Push branch, create PR, add PR link to Jira

---

### Phase 0.9: E2E RED Gate (MANDATORY before any code is written)

**If `$E2E_REPO` is unset:** Skip and continue.

Call `/e2e-verify-red $ARGUMENTS`.

**Hard block:** If RED gate fails (zero match, or test passes before implementation), STOP.
Do not proceed to Phase 1. Fix the spec or investigate pre-existing behavior before continuing.

**If RED gate passes:** `e2e.red-verified: true` is in checkpoint. Proceed to Phase 1.

---

## Phase 1: Load Plan from AgentDB (MANDATORY)

**Query AgentDB using the EXACT key that `/create-implementation-plan` stores:**

```bash
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts \
  '{"session_id": "${TENANT_NAMESPACE}", "task": "impl-plan-$ARGUMENTS.issue", "k": 1}'
```

**If not found**, try the secondary key:
```bash
npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts \
  '{"session_id": "${TENANT_NAMESPACE}", "task": "impl-$ARGUMENTS.issue", "k": 1}'
```

**If still not found**, fall back to Jira comments (look for "Implementation Plan" heading):
```bash
npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "comment"}'
```

**Extract from the plan:**
- `filesToChange` — the EXACT list of files to modify/extend (used by Phase 6.5 guardrail)
- `testsToWrite` — test files and scenarios
- `repo` and `worktreePath` — for navigation

**DO NOT start implementation without a loaded plan.** If no plan is found anywhere, STOP and print an error.

---

## Phase 2: Plan Freshness Check (MANDATORY)

> **⛔ DO NOT start implementation until this passes.**

The worktree `implementation-plan.md` may be stale if `/fix-implementation-plan` or
`/review-implementation-plan` revised the plan after the file was created. The authoritative
plan is always the **most recent plan comment on Jira** (look for "REVISED IMPLEMENTATION PLAN"
or "Implementation Plan Created" headings).

```bash
# 1. Read the worktree plan file
worktree_plan=$(cat implementation-plan.md 2>/dev/null || echo "NO_FILE")

# 2. Fetch the latest Jira comments and find the most recent plan comment
cd $PROJECT_ROOT && issue=$(npx tsx ~/.claude/skills/issues/get_issue.ts \
  '{"issue_key": "$ARGUMENTS.issue", "fields": "comment"}')
# Look for the latest comment containing "REVISED IMPLEMENTATION PLAN" or "Implementation Plan Created"
# The REVISED version (v2+) takes priority over the original

# 3. Compare: if the Jira plan mentions an endpoint/path/approach that differs from the file, STOP
```

**If the worktree file is stale or missing:**
1. Overwrite `implementation-plan.md` with the content from the latest Jira plan comment
2. Print: `[phase 2] Plan freshness check: UPDATED — worktree plan was stale, replaced with Jira v2 plan`

**If they match (or no revised plan exists on Jira):**
1. Print: `[phase 2] Plan freshness check: OK — worktree plan matches Jira`

**Quick staleness signals** (any of these means the file is stale):
- Jira has a "REVISED IMPLEMENTATION PLAN (v2)" comment but the file doesn't contain "v2" or "REVISED"
- The Jira plan references a different API endpoint than the file
- The Jira plan lists different files to change than the file

---

## Phase 3: Implementation (Context-Efficient Strategy)

**Large file strategy (>2000 lines):** When editing files larger than ~2000 lines, do NOT
read the entire file at once — this wastes context and can cause you to run out mid-task.

Instead:
1. Use `grep -n` to find the exact insertion points for each change
2. Use `Read` with `offset` and `limit` to read only the 50-100 lines around each insertion point
3. Make edits incrementally, one section at a time
4. Verify each edit with a targeted grep before moving to the next

**Apply-diff tasks:** When applying portions of a source diff to an existing file:
- Read the source diff fully (it's usually small)
- For the target file, only read sections you're about to edit
- When adding values to an EXISTING enum/list, find the existing definition first with grep —
  do NOT create a duplicate definition
- When the diff shows trigger chains in flows (e.g., `event X triggers command Y`), preserve
  the full chain — do not simplify to just the first command/event pair

---

## Phase 6: Authenticated API Testing (MANDATORY for API_ENDPOINT issues)

When implementing API endpoint fixes, you MUST test with **authenticated** requests before
creating the PR. Testing unauthenticated (getting 401) proves nothing — 401 is always the
expected unauthenticated behavior.

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

## Phase 6.5: File-Location Guardrail (MANDATORY)

> **⛔ DO NOT COMMIT until this passes.**

Compare the files you actually created/modified against the plan's `filesToChange` list.

```bash
# 1. Get list of changed files
changed_files=$(git diff --name-only HEAD)
new_files=$(git ls-files --others --exclude-standard)

# 2. For each NEW file: verify it was planned
# If a new file exists that is NOT in the plan's filesToChange list, STOP and check:
#   - Did the plan say "Extend" an existing file? If so, the new file is WRONG.
#   - Delete the new file and add the code to the planned existing file instead.

# 3. For "Extend" directives: verify the existing file was modified, NOT a new file created
# If the Jira description or plan says "Extend: path/to/existing-file.ts",
# the EXISTING file must appear in changed_files. If a DIFFERENT file was created
# at a similar path, that is a critical error.
```

**HARD RULE:** If the plan or Jira spec says "Extend: `path/to/file.ts`", you MUST modify that exact file. Creating a new file at a different path (even if similar) is a **blocking error**. Delete the wrong file and redo the work in the correct file before proceeding.

**If violations are found:**
1. Print: `[phase 6.5] FILE LOCATION VIOLATION: Created <wrong-file> but plan says extend <correct-file>`
2. Delete the wrong file

---

## Phase 6.6: Plan Compliance Check (MANDATORY)

> **⛔ DO NOT COMMIT until this passes.**

Re-read the approved plan (from Jira comments or AgentDB). Extract any explicit constraints —
statements like "Initialize real X (not mock)", "MUST use Y pattern", "NOT nil/mock mode", etc.

Then verify the implementation doesn't contradict them:

```bash
# For each "MUST NOT" / "not X" constraint in the plan, grep the new/changed files:
# Example: if plan says "Initialize real ReconciliationService (not nil/mock mode)"
# then grep for the anti-pattern in the implementation files:
changed_files=$(git diff --name-only HEAD)
# Search for patterns the plan explicitly prohibited
```

**Common local-model failure:** The plan says "use real service, not mock" but the implementation
sets the service to nil and relies on hardcoded mock responses. This produces tests that
compile and pass but provide zero coverage.

**If a constraint violation is found:**
1. Print: `[phase 6.6] PLAN COMPLIANCE VIOLATION: Plan says "<constraint>" but implementation does "<violation>"`
2. Fix the implementation to match the plan
3. Re-run validation (Phase 5)
3. Move the code into the correct file
4. Re-run validation (Phase 5)

**Deviation reporting:** If you renamed a type, omitted a planned field, or added an unplanned field,
print a `[DEVIATION]` line (e.g., `[DEVIATION] Renamed SessionPurchase → SessionItemPurchase (collision with existing type)`).
The orchestrator uses these to decide whether deviations need escalation.

---

## Phase 7: Git Staging Verification (MANDATORY)

> **⛔ DO NOT PUSH until you have verified this.**

Before committing and pushing, you MUST:

```bash
# 1. Ensure .gitignore exists and covers node_modules, dist, .env, etc.
if [ ! -f .gitignore ]; then
  echo -e "node_modules/\ndist/\n.env\n*.log\ncoverage/" > .gitignore
  git add .gitignore
fi

# 2. NEVER commit node_modules — verify it's excluded
if git ls-files --cached | grep -q '^node_modules/'; then
  git rm -r --cached node_modules/
fi

# 3. Check for untracked or unstaged files
git status

# 4. If ANY new files show as "Untracked" or modified files show as "not staged", add them:
git add <missing-files>

# 5. Pre-push sanity check — abort if node_modules or large files snuck in
staged_files=$(git diff --cached --name-only)
if echo "$staged_files" | grep -q '^node_modules/'; then
  echo "ERROR: node_modules is staged. Remove with: git rm -r --cached node_modules/"
  exit 1
fi

# 6. Block working files in repo root (plans, docs not in spec)
if echo "$staged_files" | grep -iE '^(implementation.plan|IMPLEMENTATION.PLAN)'; then
  echo "ERROR: plan files must not be committed — remove with git rm"
  exit 1
fi
if echo "$staged_files" | grep -E '^[^/]+\.md$' | grep -v -E '^(README|CLAUDE|TESTING|CHANGELOG|CONTRIBUTING|LICENSE)\.md$'; then
  echo "ERROR: unexpected .md file in repo root — working files belong in Jira/agentdb, not the repo"
  exit 1
fi

# 6. Commit (or amend if you already committed without them)
git commit  # or git commit --amend if files were missed

# 7. Push
git push -u origin <branch>

# 8. AFTER pushing, verify the push contains everything:
git diff main --stat
# The file list MUST include every file you created or modified.
# If any are missing, you forgot to stage them. Fix and force-push.
```

**Common mistakes:**
- Writing new files (e.g., `index.js`, `*.test.js`) but only committing modified files. `git add` does NOT automatically include new files unless you explicitly add them.
- Committing `node_modules/` — NEVER do this. Always verify `.gitignore` exists first.

---

## Phase 7.5: Type Sync Guard (MANDATORY for Go repos)

If the repo is `lambda-functions`, `go-common`, or `auth-service`, scan for exported Go struct
changes that may require corresponding TypeScript interface updates in `frontend-app/src/types/`.

This guard produces **warnings only** (not hard blocks) — false positives are possible since
struct names can appear in comments and test mocks. The code review step treats
`TYPE_SYNC_WARNING` lines as explicit action items.

```bash
_go_repo=false
case "$repo" in lambda-functions|go-common|auth-service) _go_repo=true ;; esac

if [ "$_go_repo" = "true" ] && [ -n "$PROJECT_ROOT" ]; then
  _changed_structs=$(git diff --name-only origin/main 2>/dev/null | \
    xargs grep -l "type.*struct" 2>/dev/null | \
    xargs grep -oh "type [A-Z][A-Za-z]* struct" 2>/dev/null | awk '{print $2}' | sort -u)

  for _struct in $_changed_structs; do
    _spa_refs=$(grep -rl "$_struct" "$PROJECT_ROOT/frontend-app/src/types/" 2>/dev/null | wc -l)
    if [ "$_spa_refs" -gt 0 ]; then
      _spa_modified=$(git -C "$PROJECT_ROOT/frontend-app" diff --name-only origin/main 2>/dev/null | \
        xargs grep -l "$_struct" 2>/dev/null | wc -l)
      if [ "$_spa_modified" = "0" ]; then
        echo "TYPE_SYNC_WARNING: $_struct modified in $repo but frontend-app/src/types/ not updated"
      fi
    fi
  done
fi
```

Review any `TYPE_SYNC_WARNING` lines before proceeding. If the struct change affects a
public-facing API shape, update the corresponding TypeScript interface in `frontend-app/src/types/`
and the OpenAPI schema before creating the PR.

---

## Phase 7.7: Local Verification Gate (MANDATORY)

**HARD GATE — PR creation blocked until all pass.**

1. Parse TESTING.md Pre-Commit Checklist from repo context (loaded in /work Phase 0.2).
2. Execute each prescribed command sequentially. If any fails, STOP and fix before retrying.
3. For frontend repos (frontend-app, dashboard):
   a. Start dev server: `npm run dev &`
   b. Wait for server ready (poll localhost:5173 or port from TESTING.md)
   c. Run Playwright smoke: `npx tsx ~/.claude/skills/playwright/screenshot.ts '{"url": "http://localhost:5173/<path>", "outputPath": "/tmp/local-verify-$ARGUMENTS.issue.png"}'`
   d. Run console check: `npx tsx ~/.claude/skills/playwright/console-check.ts '{"url": "http://localhost:5173/<path>", "failOnError": true}'`
   e. Kill dev server
   f. If screenshot shows errors or console-check fails: STOP. Fix before retrying.
4. If CGC available: `mcp__CodeGraphContext__find_dead_code` on all files touched by this issue. If dead code found, verify it is intentional (dynamic import) or fix.

---

## Phase 7.9: Pre-PR Git Sync (MANDATORY)

Before creating the PR, merge latest main into the feature branch:

```bash
git fetch origin main
git merge origin/main
```

- If merge conflicts: attempt auto-resolution. If auto-resolution fails, STOP and report conflict details to user. Do not silently drop changes.
- If new commits pulled (no conflicts): re-run the Pre-Commit Checklist from TESTING.md before proceeding to PR creation.
- If already up to date: proceed to PR creation.

---


### Phase 7.95: E2E GREEN Gate (MANDATORY before PR creation)

**If `$E2E_REPO` is unset or `e2e.not-applicable: true` in checkpoint:** Skip and continue.

**If `e2e.green-deferred: true` in checkpoint:**
This is a backend repo. GREEN will be verified post-deployment in `/validate` Phase 2.
Print: "GREEN gate deferred to /validate for backend repo. Proceeding with PR creation."
Skip to Phase 8.

**Otherwise (frontend repo):**
Call `/e2e-verify-green $ARGUMENTS`.

**Hard block:** If GREEN gate fails, STOP. Do not create the PR.
Fix the implementation, re-run Phase 3 (Implementation), and re-run this phase.
If GREEN fails more than 3 times consecutively, add label `needs-human` to the Jira issue
and stop with: "GREEN gate failed 3 times. Human review required."

**If GREEN passes:** E2E draft PR promoted. Proceed to Phase 8.

---

## Phase 8: Create PR and Link to Jira (MANDATORY)

> **⛔ DO NOT finish this command without creating the PR.**

### 7.1 Push the branch

```bash
git push -u origin <branch>
```

### 7.2 Create the PR via VCS skill

```bash
npx tsx ~/.claude/skills/vcs/create_pull_request.ts '{
  "repo": "<repo>",
  "title": "$ARGUMENTS.issue: <summary from Jira>",
  "source_branch": "<branch>",
  "description": "<what was implemented and why>"
}'
```

The skill returns JSON with the PR URL. Extract it for the next step.

### 7.3 Comment the PR link on Jira

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{
  "issue_key": "$ARGUMENTS.issue",
  "body": "PR created: <pr-url>"
}'
```

### 7.4 Update Step Label to awaiting-ci and add PR label

Add a `pr:<repo>/<number>` label so downstream commands (e.g. `/fix-pr`) can find the PR without relying on memory:

```bash
issue=$(npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "labels"}')
labels=$(echo "$issue" | jq -r '.fields.labels // [] | map(select(startswith("step:") | not) | select(startswith("pr:") | not)) + ["step:awaiting-ci", "pr:<repo>/<pr-number>"] | @json')
npx tsx ~/.claude/skills/issues/update_issue.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"labels\": $labels, \"notify_users\": false}"
```

Replace `<repo>` and `<pr-number>` with actual values from step 7.2 (e.g. `pr:test-data/49`).

### 7.5 Update Workflow Context in Memory

```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts "{\"session_id\": \"${TENANT_NAMESPACE}\", \"task\": \"active-workflow-$ARGUMENTS.issue\", \"input\": {\"issue_key\": \"$ARGUMENTS.issue\", \"step\": \"awaiting-ci\", \"branch\": \"<branch>\", \"pr_url\": \"<pr-url>\", \"last_updated\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}, \"output\": \"PR created\", \"reward\": 0.5, \"success\": false, \"critique\": \"Implementation complete, awaiting CI\"}"
```

### 7.6 Save checkpoint

```bash
python3 ~/.claude/hooks/checkpoint.py save $ARGUMENTS.issue implementation-complete '{"branch": "<branch>", "pr_created": true, "repo": "<repo>", "pr_number": <pr-number>}'
```

---

**START NOW: Begin Phase 0/Step 0.**

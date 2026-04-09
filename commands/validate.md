<!-- MODEL_TIER: opus (orchestrator) -->
---
description: Validate a deployed Jira issue and transition to Done with evidence (use after /work)
arguments:
  - name: issue
    description: Jira issue key (e.g., PROJ-123) - must be in VALIDATION status
    required: true
---

# Validate Deployed Issue: $ARGUMENTS.issue

You are an **orchestrator**. Your job is to dispatch sub-commands and verify their results.
**DO NOT do test execution, evidence collection, or deployment checking yourself.**
Each sub-command is self-contained. You dispatch them in order and verify results between phases.

> **Note:** The `--team` flag is deprecated. This orchestrator dispatches sub-commands to local
> models, replacing the agent team pattern. Remove `--team` from any scripts calling `/validate`.

---

## How to Dispatch Sub-Commands

### Dispatch Whitelist (MANDATORY — overrides resolve-model.py)

Only these commands run **inline on Opus** (judgment and high-stakes operations):
- `/validate-evaluate` — judgment call, compares results vs criteria. Short operation.
- `/validate-transition` — high-stakes Jira state mutation. Local models fail on
  transition edge cases and skip label updates. Opus runs this inline cheaply.
- **Phase 2.75 quality gate** — auth verification after `/validate-run-tests`. Local models
  frequently fail multi-step SRP auth and rationalize the failure. Opus catches this.

**ALL other sub-commands MUST be dispatched via `dispatch-local.sh`**, regardless of
what `resolve-model.py` returns.

### Dispatch Procedure

- If the command is **NOT in the inline whitelist above**: dispatch via script:
  ```bash
  ~/.claude/hooks/dispatch-local.sh <command-name> <args>
  ```

- If the command **IS in the inline whitelist**: do the work yourself directly
  (read files, call Jira skills, evaluate criteria). Do NOT dispatch.

`dispatch-local.sh` handles everything: env vars, AWS/Jira/Bitbucket creds, Ollama config,
prompt enrichment (e.g. pre-fetching issue context), progress display,
and result extraction.

**Do NOT construct env -i / claude subprocess commands manually.** Always use dispatch-local.sh.

**IMPORTANT dispatch rules:**
- **Set timeout to 900000** (15 minutes) on each dispatch Bash call
- **Do NOT use run_in_background** — you must wait for the result before proceeding
- Read the output before moving to the next phase — the output contains repo name, test results, etc.

---

## Phase 0: Resume Check

```bash
checkpoint=$(python3 ~/.claude/hooks/checkpoint.py load $ARGUMENTS.issue 2>/dev/null || echo '{"found":false}')
```

If checkpoint found with a completed `val.*` phase, skip to the next incomplete phase.
Orchestrator phases use `val.` prefix to avoid collision with `/work` orchestrator checkpoints.

**Phase name mapping:**
- `val.phase0.75-blocker` → Code review blocker found, skip to Phase 6
- `val.phase0.6-complete` → Visual impact classified (contains `has_visual_effects`, `ui_paths`), skip re-classifying
- `val.phase1f-complete` → File-verification done (fast path), skip to Phase 4
- `val.phase1p-complete` → Pipeline-verification done (source verified), skip to Phase 4
- `val.phase1-pending` → Deploy was in progress last run, resume Phase 1 polling with saved build ID
- `val.phase1-complete` → Deploy check done (contains `repo`), skip to Phase 2
- `val.phase2-complete` → Tests done (contains `passed`/`failed` counts), skip to Phase 2.75
- `val.phase2.75-complete` → Auth quality gate passed (may contain `auth_remediated`), skip to Phase 3
- `val.phase3-complete` → Evidence collected, skip to Phase 4
- `val.phase4-complete` → Verdict produced (contains `recommendation`), skip to Phase 5

**Fast-path checkpoint optimization:** On the fast path (file-verification repos), only save
checkpoints at Phase 1F and Phase 4. Skip the Phase 0.5 classification checkpoint — it's
trivial to recompute from labels + CLAUDE.md.

---

## Phase 0.75: Code Review Blocker Check (INLINE — Opus)

This runs inline on Opus. Do NOT dispatch. Costs ~100 tokens.

Scan the Jira comments (already fetched in Phase 0.5) for the most recent code review verdict.
Look for comments containing `### Verdict:` — the code review skill writes these.

**If the most recent review verdict is `REQUIRES REWORK`:**
- Skip all subsequent phases
- Set verdict to `TRANSITION_TODO`
- Post a short comment: "Validation skipped — unresolved code review: REQUIRES REWORK"
- Transition to To Do, update labels (remove `step:validating`, add `outcome:validation-skipped`)
  - Use `outcome:validation-skipped` (NOT `outcome:validation-failed`) — this signals that
    validation was skipped due to a process issue (stale review verdict), not because the code
    itself failed. `/work` uses this distinction to avoid unnecessary rework cycles.
- Jump to Phase 6 (cost capture)

**If no review comment or verdict is APPROVED/LGTM:** proceed normally.

**If zero comments exist on the issue:** note "No code review on record" in the Phase 4 report
under a `### Notes` section. This is informational only — not a blocker.

---

## Phase 0.5: Classify Validation Type (INLINE — Opus)

This runs inline on Opus. Do NOT dispatch. Costs ~200 tokens.

```bash
npx tsx ~/.claude/skills/jira/worklog_identity.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"phase\": \"starting\", \"command\": \"/validate\", \"message\": \"Beginning post-deployment validation\"}" 2>/dev/null || true
```

**Purpose:** Determine whether this issue requires runtime deployment verification or can be
validated entirely via file checks and local CLI commands.

1. Extract the repo from Jira labels (e.g. `repo-project-docs` → `project-docs`)
2. Ensure the repo is cloned locally (local models and inline phases need it):
   ```bash
   if [ ! -d "$PROJECT_ROOT/${repo}" ]; then
     # Clone via VCS-appropriate URL (resolved by git remote or config)
     cd $PROJECT_ROOT && git clone git@bitbucket.org:your-org/${repo}.git
     # Note: GitHub repos (e.g. sdk) may need: gh repo clone Mission-Sciences/<remote_repo> ${repo}
   fi
   ```
3. Read the repo's CLAUDE.md validation profile:
   ```bash
   grep -A 6 "## Validation Profile" $PROJECT_ROOT/<repo>/CLAUDE.md 2>/dev/null
   ```
3. Parse `deploy-strategy` and `validation-type` from the profile.

**Routing decision:**

| deploy-strategy | validation-type | Route |
|----------------|-----------------|-------|
| `none` | `file-verification` | **Fast path** — skip Phase 1, go to Phase 1F |
| `none` | `integration` | **Fast path** with local integration commands |
| `concourse` / `manual` | `pipeline-verification` | **Pipeline path** — Phase 1 (deploy check) + Phase 1P (source verification), skip Phases 2-3 |
| `concourse` / `manual` | `runtime` | **Full path** — Phase 1 as normal |
| (missing profile) | (any) | **Full path** — assume runtime, log warning in report. **NEVER downgrade to file-verification or pipeline-verification without an explicit profile.** Most repos have Concourse pipelines even if undocumented. |

**IMPORTANT — `code_repo` is authoritative for Phases 2-3:**
The label-derived repo (e.g. `dashboard`) is the `code_repo` — where the source code and tests live.
Phase 1 may return a different `deploy_repo` (e.g. `frontend-app`) because some repos deploy through another
repo's pipeline. Always pass `code_repo` (not Phase 1's REPO) to Phases 2 and 3.

Save classification (full path only — skip on fast path, trivial to recompute):
```bash
# Only save if route is "full"
python3 ~/.claude/hooks/checkpoint.py save $ARGUMENTS.issue val.phase0.5-complete '{"code_repo":"<repo>","deploy_strategy":"<strategy>","validation_type":"<type>","route":"full"}'
```

---

## Phase 0.6: Visual Impact Classification (INLINE — Opus)

This runs inline on Opus. Do NOT dispatch. Costs ~150 tokens.

**Purpose:** Determine whether this change has user-visible effects in frontend-app, regardless of which repo the code lives in. Backend changes (lambda-functions, core-infra, go-common) frequently produce visible UI behavior — session listings, token balances, marketplace entries, organization data — that must be validated with Playwright, not just curl. Without this step, evidence collection for backend repos skips screenshots entirely, causing false-positive validations.

Using the issue description and acceptance criteria already in context, determine:

1. **`has_visual_effects`** — set to `true` if ANY of these apply:
   - Acceptance criteria mention something a user "sees", "views", "displays", "shows", or "navigates to"
   - The issue is a bug about missing or broken UI behavior (sidebar, page, link, component)
   - The repo is `frontend-app` or `e2e-tests` (always visual)
   - The change affects data that frontend-app renders: sessions, SMART token balances, marketplace listings, organizations, applications, user profiles, datasets, identity verification, publisher info
   - Set to `false` **only** if the change is pure infrastructure with no user-facing data: VPC, IAM policies, S3 bucket config, DynamoDB table schema changes that don't add new data columns, or security/cert rotation

2. **`ui_paths`** — list the frontend-app route paths most likely to show the change. Use empty array `[]` only if `has_visual_effects` is false. Examples:
   - Session or marketplace changes → `["/marketplace", "/sessions"]`
   - Token/balance changes → `["/marketplace", "/tokens"]`
   - Organization/membership changes → `["/settings/organization"]`
   - Sidebar or navigation bug → `["/marketplace"]` (root, which shows sidebar)
   - Application/publisher changes → `["/marketplace", "/applications"]`
   - User profile/identity changes → `["/settings/profile"]`
   - Datasets changes → `["/datasets"]`
   - Admin/dashboard changes → `["/admin"]`

Save result to checkpoint (run regardless of route — fast path and pipeline path also need this):
```bash
python3 ~/.claude/hooks/checkpoint.py save $ARGUMENTS.issue val.phase0.6-complete '{"has_visual_effects":<true|false>,"ui_paths":[<paths as JSON array of strings>]}'
```

> **This checkpoint is read by `dispatch-local.py`** when building the enriched prompts for `validate-run-tests` and `validate-collect-evidence`. It ensures that even when a backend repo is being validated, the local model receives explicit Playwright instructions with concrete page paths.

---

## Phase 1F: File-Verification Fast Path (INLINE — Opus)

**Only runs when Phase 0.5 routes to fast path (deploy-strategy: none).** Skip Phase 1, 2, 3 entirely.

This phase replaces Phases 1-3 for repos where merge-to-main IS the deliverable —
meaning repos with **NO CI/CD pipeline at all** (e.g. pure documentation repos like project-docs).

**CRITICAL: If the repo has a Concourse pipeline (even just for build/test/seed), it is NOT
a file-verification repo.** Use pipeline-verification or full path instead. The existence of
a Concourse pipeline means there is a post-merge job that must be verified as green.
Do NOT confuse PR-check pipelines (pre-merge CI) with post-merge deploy pipelines.

1. Verify the PR is merged:
   ```bash
   # Extract PR number from labels (e.g. pr:project-docs/38 → 38)
   npx tsx ~/.claude/skills/vcs/get_pull_request.ts '{"repo": "<repo>", "pr_number": <pr_number>}'
   ```
   Confirm state is `MERGED`. If not merged, verdict is `TRANSITION_TODO` — stop here.

2. Fetch acceptance criteria from Jira (already have the issue from Phase 0).

3. For each acceptance criterion, run the appropriate verification command:
   - File content checks: `grep` / `jq` against repo files
   - CLI validation: run commands from the validation profile's `validation-commands`
   - Capture command output as evidence

4. Write results to `/tmp/validate-$ARGUMENTS.issue-test-results.txt` and
   `/tmp/validate-$ARGUMENTS.issue-evidence.txt` in the same format as Phases 2-3.

5. Save checkpoint:
   ```bash
   python3 ~/.claude/hooks/checkpoint.py save $ARGUMENTS.issue val.phase1f-complete '{"status":"file-verified","passed":<N>,"failed":<M>,"total":<T>,"pr_merged":true}'
   ```

6. Proceed directly to Phase 4 (Evaluate Results) with the collected evidence.

---

## Phase 1P: Pipeline-Verification Path (INLINE — Opus)

**Only runs when Phase 0.5 routes to `pipeline-verification`.** Replaces Phases 2-3.

For repos where the CI pipeline executing successfully IS the runtime proof (e.g., metrics
calculators, data pipelines, CLI tools, test-data seeders). The code runs inside the pipeline —
a green post-merge build means the code executed without error.

**CRITICAL: Pre-merge vs post-merge pipelines are DIFFERENT things.**
- **PR-check pipeline** (pre-merge): Runs on the feature branch before merge. Implementation
  comments citing "Concourse pr-check succeeded" refer to THIS. It proves the code compiles
  and tests pass, but does NOT prove the code was deployed/seeded to any environment.
- **Post-merge main pipeline**: Runs after merge to main. THIS is what `/validate` must verify.
  It builds from main and deploys/seeds to the target environment.

Never accept implementation comments about CI as evidence of post-merge deployment.
Only Phase 1 (validate-deploy-status checking the main job in Concourse) provides that evidence.

1. Run Phase 1 (deploy status check) as normal to confirm the **post-merge main pipeline** is green.

2. Read the changed source files to verify acceptance criteria in code:
   ```bash
   # Find the PR for this issue
   npx tsx ~/.claude/skills/vcs/list_pull_requests.ts '{"repo": "<repo>", "state": "closed"}'
   # Filter for the issue key in the title, then read files from the local clone on main
   cd $PROJECT_ROOT/<repo> && git pull origin main
   # Read each file mentioned in the issue's FILES TO CHANGE section from the local repo
   ```

3. For each acceptance criterion, verify against the actual source code and test files.
   This is stronger evidence than inferring from build success.

4. If the validation profile includes `validation-commands`, run them locally if the repo
   is available, or note them as "verified via CI" if not.

5. Write results to `/tmp/validate-$ARGUMENTS.issue-test-results.txt` and
   `/tmp/validate-$ARGUMENTS.issue-evidence.txt` in the standard format.

6. Save checkpoint:
   ```bash
   python3 ~/.claude/hooks/checkpoint.py save $ARGUMENTS.issue val.phase1p-complete '{"status":"pipeline-verified","passed":<N>,"failed":<M>,"total":<T>,"pr_merged":true}'
   ```

7. Proceed directly to Phase 4 (Evaluate Results) with the collected evidence.

---

## Phase 1: Check Deployment Status

**Only runs when Phase 0.5 routes to full path or pipeline-verification.** Skipped for file-verification repos.

Dispatch: `/validate-deploy-status $ARGUMENTS.issue`

```bash
~/.claude/hooks/dispatch-local.sh validate-deploy-status "$ARGUMENTS.issue"
```

Parse the output for:
- `DEPLOY_STATUS:` — must be `DEPLOYED` to proceed
- `REPO:` — this is the `deploy_repo` (pipeline identity). It may differ from `code_repo` (e.g. frontend-app vs dashboard). Do NOT pass this to Phases 2-3; use `code_repo` from Phase 0.5 instead.
- `ENV_URL:` — the deployed environment URL (e.g. `https://dev.example.com`)

**If DEPLOY_STATUS is NEEDS_DEPLOY:**
- Skip Phases 2-3 (no point testing/collecting evidence for undeployed code)
- Go directly to Phase 4 with a pre-set verdict of `NEEDS_DEPLOY`
- Include the DEPLOY_GAP_REASON in the report
- Continue to Phase 5 (transition with NEEDS_DEPLOY verdict)

**If DEPLOY_STATUS is FAILED:** Stop and report to user. Do not proceed.

**If DEPLOY_STATUS is IN_PROGRESS:** Poll with timeout before giving up.

1. Save the BUILD_ID from the initial dispatch.
2. Poll up to 10 times, waiting 60 seconds between attempts:
   ```bash
   for attempt in $(seq 1 10); do
     echo "Deploy poll attempt $attempt/10 — waiting 60s..."
     sleep 60
     result=$(~/.claude/hooks/dispatch-local.sh validate-deploy-status "$ARGUMENTS.issue")
     status=$(echo "$result" | sed -n 's/.*DEPLOY_STATUS: \([A-Z_]*\).*/\1/p')
     if [ "$status" = "DEPLOYED" ]; then
       break
     elif [ "$status" = "FAILED" ]; then
       echo "Deploy failed during polling. Stopping."
       break
     fi
   done
   ```
3. After the loop:
   - **DEPLOYED** → continue to Phase 2 as normal
   - **FAILED** → stop and report to user
   - **Still IN_PROGRESS after 10 attempts** → save a pending checkpoint and exit:
     ```bash
     python3 ~/.claude/hooks/checkpoint.py save $ARGUMENTS.issue val.phase1-pending '{"status":"in_progress","build_id":"<build_id>","repo":"<repo>","env_url":"<url>","poll_exhausted":true}'
     ```
     Report to user: "Deploy build <BUILD_ID> still in progress after 10 minutes. Run `/validate $ARGUMENTS.issue` again once the build completes — Phase 1 will resume from checkpoint."

**On resume from `val.phase1-pending` checkpoint:** Skip the initial dispatch. Instead, go straight
to polling with the saved BUILD_ID — dispatch `/validate-deploy-status` and check if the build
has completed since last run. If DEPLOYED on first check, continue. If still IN_PROGRESS, resume
the poll loop for the remaining attempts.

**Verification:** The orchestrator confirms DEPLOY_STATUS and REPO were actually extracted from the output.
If the local model returned no structured output, re-dispatch once with explicit instructions.

### Phase 1 Addendum: API Gateway Stage Freshness Check

**For lambda-functions API Gateway issues only.** After confirming DEPLOY_STATUS is DEPLOYED, verify
the API Gateway stage was actually redeployed (not stale from a previous deployment):

```bash
API_ID=$(aws apigateway get-rest-apis --profile ${AWS_PROFILE_DEV} --region us-east-1 \
  --query 'items[?name==`api-service-dev`].id' --output text)
STAGE_DATE=$(aws apigateway get-stage --rest-api-id "$API_ID" --stage-name "v1" \
  --profile ${AWS_PROFILE_DEV} --region us-east-1 --query 'lastUpdatedDate' --output text)
echo "STAGE_LAST_UPDATED: $STAGE_DATE"
```

Compare `STAGE_LAST_UPDATED` against the Concourse build timestamp from Phase 1.
If the stage is older than the latest successful `deploy-api-gateway-dev` build, the stage
is **stale** — the Concourse build may have succeeded but the terraform deployment failed
silently (see PROJ-4412). In this case:
- Set verdict to `TRANSITION_TODO`
- Root cause: "API Gateway stage stale — last updated $STAGE_DATE, build completed later"
- Check Concourse build logs for terraform errors that were silently swallowed

Save checkpoint:
```bash
python3 ~/.claude/hooks/checkpoint.py save $ARGUMENTS.issue val.phase1-complete '{"status":"deployed","repo":"<repo>","env_url":"<url>"}'
```

---

### Phase 2.0: E2E GREEN Gate (backend repos only)

**If `$E2E_REPO` is unset:** Skip.

**If checkpoint does NOT contain `e2e.green-deferred: true`:** Skip (already verified pre-PR).

**If `e2e.not-applicable: true` in checkpoint:** Skip.

**If `e2e.green-deferred: true` in checkpoint:**
Call `/e2e-verify-green $ARGUMENTS` as the FIRST step before any other tests.

**If GREEN fails:**
- Set verdict to `TRANSITION_TODO` immediately
- Print: "E2E GREEN gate failed post-deployment. Verdict: TRANSITION_TODO. Do not collect further evidence."
- Skip to Phase 5 (transition) with `TRANSITION_TODO`

**If GREEN passes:**
- `e2e.green-verified: true` written to checkpoint
- E2E draft PR promoted to ready-for-review
- Continue with normal Phase 2 test execution

---

## Phase 2: Run Validation Tests

Dispatch: `/validate-run-tests $ARGUMENTS.issue <code_repo> <env_url>`

```bash
~/.claude/hooks/dispatch-local.sh validate-run-tests "$ARGUMENTS.issue <code_repo> <env_url>"
```

Use `code_repo` from Phase 0.5 (label-derived) and `env_url` from Phase 1. Do NOT use Phase 1's REPO here — it may be a different repo (e.g. `frontend-app` when the code lives in `dashboard`).

Parse the output for:
- `PASSED:` / `FAILED:` / `TOTAL:` counts
- Per-criterion results between `TEST_RESULTS_START` and `TEST_RESULTS_END`

**Verification:** Check that test results file exists:
```bash
cat /tmp/validate-$ARGUMENTS.issue-test-results.txt 2>/dev/null | head -5
```

If the file doesn't exist but the output contains test results, that's acceptable — extract
from output. If neither exists, re-dispatch once.

Save checkpoint:
```bash
python3 ~/.claude/hooks/checkpoint.py save $ARGUMENTS.issue val.phase2-complete '{"status":"tests-run","passed":<N>,"failed":<M>,"total":<T>}'
```

---

## Phase 2.75: Auth Quality Gate (INLINE — Opus)

This runs inline on Opus. Do NOT dispatch. Costs ~300 tokens normally, more if remediation needed.

**Purpose:** The local model frequently fails the multi-step SRP authentication procedure and then
rationalizes the failure (e.g., "API Gateway uses IAM auth" when it actually mangled the Bearer header,
or reports PARTIAL instead of retrying auth). This gate catches that and remediates before proceeding.

### Step 1: Check AUTH_STATUS from Phase 2

Read the test results file:
```bash
cat /tmp/validate-$ARGUMENTS.issue-test-results.txt 2>/dev/null
```

Parse `AUTH_STATUS:` from the output. Also count how many criteria have `AUTHENTICATED: false`.

### Step 2: Evaluate auth outcome

| AUTH_STATUS | Authenticated criteria | Action |
|-------------|----------------------|--------|
| `AUTHENTICATED` | All or most `true` | **PASS** — proceed to Phase 3 |
| `AUTH_NOT_REQUIRED` | N/A (file/infra checks) | **PASS** — proceed to Phase 3 |
| `AUTH_FAILED` | All `false` | **REMEDIATE** — run auth yourself (Step 3) |
| `AUTHENTICATED` | Some `false` | **PARTIAL** — re-test only the unauthenticated criteria (Step 3) |

### Step 3: Remediate (run SRP auth inline)

If the local model failed auth, the orchestrator runs authentication and re-tests:

```bash
# 1. Ensure testData.json exists
if [ ! -f $PROJECT_ROOT/e2e-tests/tests/fixtures/testData.json ]; then
  cd $PROJECT_ROOT/e2e-tests && npm install --silent 2>/dev/null && npm run test-data:download
fi

# 2. Get credentials
ROLE="org_admin"
CREDS=$(cat $PROJECT_ROOT/e2e-tests/tests/fixtures/testData.json | jq -r --arg role "$ROLE" '[.[] | select(.role == $role)][0] | "\(.email) \(.password) \(.orgId)"')
EMAIL=$(echo "$CREDS" | awk '{print $1}')
PASSWORD=$(echo "$CREDS" | awk '{print $2}')
ORG_ID=$(echo "$CREDS" | awk '{print $3}')

# 3. SRP auth (oauth-test-cli client, no secret needed)
TOKEN=$(node ~/.claude/skills/cognito-srp-token.js "$EMAIL" "$PASSWORD" dev)

# 4. Verify token is valid (non-empty, starts with eyJ)
echo "$TOKEN" | head -c 10
```

If the token is valid (`eyJ...`), re-test each criterion that had `AUTHENTICATED: false`:
```bash
curl -s -w '\nHTTP %{http_code}' \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  "https://api.dev.example.com/<path>"
```

**Update the test results file** with the corrected results. Overwrite `/tmp/validate-$ARGUMENTS.issue-test-results.txt`
with the merged results (local model's passing criteria + orchestrator's re-tested criteria).

Update the Phase 2 checkpoint with corrected counts:
```bash
python3 ~/.claude/hooks/checkpoint.py save $ARGUMENTS.issue val.phase2-complete '{"status":"tests-run","passed":<N>,"failed":<M>,"total":<T>,"auth_remediated":true}'
```

### Step 4: If SRP auth also fails for orchestrator

If `cognito-srp-token.js` returns an empty/invalid token even for Opus:
1. Log the error: "AUTH_UNAVAILABLE: SRP auth failed for both local model and orchestrator"
2. Do NOT mark criteria as PASS — leave them as FAIL
3. Add `auth_broken: true` to the checkpoint
4. Proceed to Phase 3 — the evidence collection may still capture useful artifacts
5. Phase 4 should factor in `auth_broken` when producing the verdict

### Playwright Auth Schema (MANDATORY — read before dispatching Phase 3)

Playwright authentication is **always available** in the dev environment. If Phase 3 evidence
shows login-page screenshots, it indicates a **wrong auth schema in the skill call**, not missing
auth infrastructure. Auth failures silently redirect to login rather than throwing errors.

**Correct Playwright screenshot auth schema (`auth` MUST be nested):**
```bash
npx tsx ~/.claude/skills/playwright/screenshot.ts \
  '{"url": "https://dev.example.com/...", "outputPath": "/tmp/...",
    "auth": {"env": "dev", "role": "org_admin"}}'
```

**WRONG — `role` at top level silently redirects to login (DO NOT USE):**
```bash
# '{"url": "...", "outputPath": "/tmp/...", "role": "org_admin"}'  ← WRONG: auth not nested
```

**Anti-pattern diagnosis:** If a screenshot shows a login/auth page, do NOT assume the
feature is broken or auth is unavailable. Re-take the screenshot with the correct nested
`"auth"` schema. If it still shows login, check credentials in `~/.claude/e2e-config.json`.

---

## Phase 2.5: Authenticated API Testing (INLINE — Opus, MANDATORY for API_ENDPOINT issues)

This runs inline on Opus. Do NOT dispatch. The checks are lightweight (a few CLI calls).

### Preferred Method: test-invoke-method (RECOMMENDED)

`test-invoke-method` is the **most reliable** way to verify Lambda integration. It bypasses
auth entirely and shows the full execution log (Lambda ARN, latency, request/response bodies).
Use this as the PRIMARY verification for any API endpoint issue:

```bash
API_ID=$(aws apigateway get-rest-apis --profile ${AWS_PROFILE_DEV} --region us-east-1 \
  --query 'items[?name==`api-service-dev`].id' --output text)
RESOURCE_ID=$(aws apigateway get-resources --rest-api-id "$API_ID" --profile ${AWS_PROFILE_DEV} \
  --region us-east-1 --query "items[?path=='<path>'].id" --output text)
aws apigateway test-invoke-method --rest-api-id "$API_ID" \
  --resource-id "$RESOURCE_ID" --http-method GET \
  --headers '{"X-Organization-Id":"<org_id>","Authorization":"Bearer <token>"}' \
  --path-with-query-string "<full-path>" \
  --profile ${AWS_PROFILE_DEV} --region us-east-1
```

**What to look for in the execution log:**
- `Endpoint request URI: https://lambda.../<function-name>/invocations` — proves Lambda wiring
- `Integration latency: Xms` — proves Lambda executed
- `Endpoint response body` — shows the actual Lambda response
- Status 401/403 from Lambda ( not API Gateway) still proves wiring works

**Interpretation:** A 500 from test-invoke with a Lambda URI in the log = wiring works, Lambda
has a bug. A 401 from the Lambda's own auth = wiring works, test user lacks access. Only a
404 "No method found" or missing Lambda URI means wiring is broken.

**Fallback to curl:** Only use curl-based testing when test-invoke-method is unavailable
(e.g., rate-limited) or when you need to verify the full auth chain end-to-end.

### Step 1: Route Existence Pre-Check (MANDATORY — run BEFORE auth testing)

API Gateway returns 403 "Missing Authentication Token" for ANY path when IAM auth is
configured — **including non-existent routes**. PROJ-2501 wasted a full validation cycle
because 403 was misread as "endpoint exists, auth failing." Always verify routes first:

```bash
API_ID=$(aws apigateway get-rest-apis --profile ${AWS_PROFILE_DEV} --region us-east-1 \
  --query 'items[?name==`api-service-dev`].id' --output text)
aws apigateway get-resources --rest-api-id "$API_ID" --profile ${AWS_PROFILE_DEV} --region us-east-1 \
  --query "items[?contains(path, '<keyword>')].path" --output json
```

If zero routes match, **stop** — the issue is missing API Gateway wiring, not a code bug.
Set verdict to `TRANSITION_TODO` with root cause "API Gateway routes not configured."

### Step 2: Determine Auth Method

Check the API Gateway method authorization type for one of the endpoints:

```bash
# Get resource ID for one endpoint path
RESOURCE_ID=$(aws apigateway get-resources --rest-api-id "$API_ID" --profile ${AWS_PROFILE_DEV} \
  --region us-east-1 --query "items[?path=='<path>'].id" --output text)
aws apigateway get-method --rest-api-id "$API_ID" --resource-id "$RESOURCE_ID" \
  --http-method GET --profile ${AWS_PROFILE_DEV} --region us-east-1 \
  --query 'authorizationType' --output text
```

| authorizationType | Auth method |
|-------------------|-------------|
| `CUSTOM` or `COGNITO_USER_POOLS` | **Cognito JWT** (Step 3a) |
| `AWS_IAM` | **SigV4** (Step 3b) |
| `NONE` | No auth needed — test directly |

### Step 3a: Cognito JWT Auth

```bash
# 1. Get test credentials (from e2e-tests)
cd $PROJECT_ROOT/e2e-tests && npm install --silent 2>/dev/null && npm run test-data:download
ORG_ADMIN=$(node -e "const d=JSON.parse(require('fs').readFileSync('tests/fixtures/testData.json'));const u=(Array.isArray(d)?d:d.users).find(u=>u.role==='org_admin');console.log(JSON.stringify(u))")
EMAIL=$(echo "$ORG_ADMIN" | jq -r .email)
PASSWORD=$(echo "$ORG_ADMIN" | jq -r .password)
ORG_ID=$(echo "$ORG_ADMIN" | jq -r .orgId)
POOL_ID="us-east-1_yMqRDIh9x"
CLIENT_ID="7979i07oaa25vqc95eke44bfee"
CLIENT_SECRET=$(aws cognito-idp describe-user-pool-client --user-pool-id "$POOL_ID" --client-id "$CLIENT_ID" --profile ${AWS_PROFILE_DEV} --region us-east-1 --query 'UserPoolClient.ClientSecret' --output text)
SECRET_HASH=$(echo -n "${EMAIL}${CLIENT_ID}" | openssl dgst -sha256 -hmac "$CLIENT_SECRET" -binary | base64)
TOKEN=$(aws cognito-idp admin-initiate-auth --user-pool-id "$POOL_ID" --client-id "$CLIENT_ID" --auth-flow ADMIN_USER_PASSWORD_AUTH --auth-parameters USERNAME="$EMAIL",PASSWORD="$PASSWORD",SECRET_HASH="$SECRET_HASH" --profile ${AWS_PROFILE_DEV} --region us-east-1 | jq -r '.AuthenticationResult.IdToken')
curl -s -w '\nHTTP %{http_code}' \
  -H "Authorization: Bearer $TOKEN" -H "X-Organization-Id: $ORG_ID" \
  "https://api.dev.example.com/<path>"
```

### Step 3b: IAM SigV4 Auth

```bash
# Uses AWS CLI's built-in SigV4 signing via api-gateway endpoint invocation
aws apigateway test-invoke-method --rest-api-id "$API_ID" \
  --resource-id "$RESOURCE_ID" --http-method GET \
  --profile ${AWS_PROFILE_DEV} --region us-east-1 \
  --query '{status:status,body:body}' --output json
```

If `test-invoke-method` isn't available for the resource, use `awscurl` or the Python
`requests-aws4auth` approach. Search AgentDB for the latest procedure:
```bash
npx tsx ~/.claude/skills/agentdb/pattern_search.ts '{"task": "authenticated API testing"}'
```

### Interpretation

**CRITICAL traps — do NOT misread these responses:**

| Response | Meaning | Action |
|----------|---------|--------|
| 403 "Missing Authentication Token" (unauthenticated) | Generic API the project response for ANY path with IAM auth | Proves nothing — run Step 1 |
| 401 (unauthenticated) | Expected Cognito rejection | Proves nothing — authenticate first |
| 404 "No method found" (authenticated) | Route does NOT exist in API Gateway | TRANSITION_TODO — missing wiring |
| 200/201 with response body | Endpoint works | Record as evidence |
| 500 with `{"error":"internal server error"}` (authenticated) | Lambda reached but errored (e.g., bad app_id) | **Proves wiring works** — Lambda integration is functional |
| 401 `{"error":"unauthorized"}` from Lambda (via test-invoke log) | Lambda auth rejected request | **Proves wiring works** — Lambda executed its own auth check |

---

## Phase 3: Collect Evidence

Dispatch: `/validate-collect-evidence $ARGUMENTS.issue <code_repo> <env_url>`

```bash
~/.claude/hooks/dispatch-local.sh validate-collect-evidence "$ARGUMENTS.issue <code_repo> <env_url>"
```

Use `code_repo` from Phase 0.5, same as Phase 2.

Parse the output for evidence manifest between `EVIDENCE_START` and `EVIDENCE_END`.

**Verification:** Check evidence files exist:
```bash
ls /tmp/validate-$ARGUMENTS.issue-* 2>/dev/null
```

Save checkpoint:
```bash
python3 ~/.claude/hooks/checkpoint.py save $ARGUMENTS.issue val.phase3-complete '{"status":"evidence-collected","artifact_count":<N>}'
```

---

## Phase 3.5: Functional Smoke Regression Check (INLINE — Opus)

**Only runs on the full path (not fast-path or pipeline-verification).**

After evidence collection, run the functional smoke test and compare against the stored
AgentDB baseline to surface any regressions introduced by this or adjacent changes:

```bash
if [ -f "$PROJECT_ROOT/lambda-functions/tests/smoke/smoke-test.js" ]; then
  node "$PROJECT_ROOT/lambda-functions/tests/smoke/smoke-test.js" \
    --env dev --output /tmp/smoke-$ARGUMENTS.issue.json 2>&1 || true

  # Compare against baseline stored in AgentDB
  baseline=$(npx tsx ~/.claude/skills/agentdb/pattern_search.ts \
    '{"task": "smoke-baseline-lambda-functions-dev", "k": 1}' 2>/dev/null || echo '{"results":[]}')
  baseline_results=$(echo "$baseline" | jq -r '.results[0].approach // ""')

  if [ -n "$baseline_results" ] && [ -f /tmp/smoke-$ARGUMENTS.issue.json ]; then
    new_failures=$(jq -n \
      --argjson current "$(cat /tmp/smoke-$ARGUMENTS.issue.json)" \
      --argjson prior "$baseline_results" \
      '[($prior | if type == "string" then fromjson else . end).results[]? |
        select(.status == "pass") | .name as $n |
        $current.results[]? | select(.name == $n and .status == "fail")] | length' 2>/dev/null || echo 0)
    if [ "$new_failures" -gt 0 ]; then
      echo "REGRESSION_DETECTED: $new_failures smoke test(s) now failing that were passing in baseline."
      echo "This will cause verdict TRANSITION_TODO in Phase 4."
      echo "SMOKE_REGRESSION=true" >> /tmp/validate-$ARGUMENTS.issue-test-results.txt
    fi
  fi
fi
```

Phase 4 should check for `SMOKE_REGRESSION=true` in the test results file and include it
as evidence of regression when producing the verdict.

After a clean `TRANSITION_DONE`, update the baseline in AgentDB:
(This runs in Phase 5 after successful transition — see Phase 5 TRANSITION_DONE section.)

---

### Phase 4.0: Include E2E Verdict

Call `/e2e-interpret $ARGUMENTS`.

The `E2E_VERDICT` from `/e2e-interpret` is included in the evaluation context.
**A FAIL `E2E_VERDICT` overrides any passing unit/integration test evidence.**
Verdict CANNOT be `TRANSITION_DONE` if `E2E_VERDICT` is FAIL or BLOCKED.


### Phase 4.1: Playwright Test Failure Hard Gate (INLINE — Opus)

**HARD GATE — cannot be overridden by caveats or infrastructure exemptions.**

If code_repo is e2e-tests AND Phase 2 test results contain any FAILED Playwright test:
- Set verdict to TRANSITION_TODO immediately
- Do NOT enter Phase 4 evaluation — the verdict is predetermined
- Rationale: "Playwright journey tests failed. e2e-tests test failures are never infrastructure
  issues — they are test failures. Verdict: TRANSITION_TODO."
- Skip to Phase 5 with TRANSITION_TODO

Additionally, for ANY repo: if acceptance criteria explicitly require "tests run without
errors" (or equivalent phrasing) AND test results show errors → set verdict to
TRANSITION_TODO. Do NOT allow caveats to override explicit test-passing requirements.

**Background:** PROJ-2613 was validated as Done despite journey tests observing a black screen
crash because the orchestrator allowed TRANSITION_DONE with a "caveat". This gate prevents
that class of error.


---

## Phase 4: Evaluate Results (INLINE — Opus)

This runs inline on Opus. Do NOT dispatch.

Before evaluating, assemble blocker state from prior phases:
- `deploy_status` from Phase 1 checkpoint
- `evidence_quality` from Phase 3 checkpoint (EVIDENCE_QUALITY field)
- `test_failures` from Phase 2 checkpoint (FAILED count)

Pass these as context for contradiction detection.

1. Read the test results (from checkpoint data or `/tmp/validate-$ARGUMENTS.issue-test-results.txt`)
2. Read the evidence manifest (from `/tmp/validate-$ARGUMENTS.issue-evidence.txt`)
3. Fetch validation criteria from Jira:
   ```bash
   npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "description,comment"}'
   ```

4. For each validation criterion, match it to test results and evidence.

### 4a: Contradiction Detection (MANDATORY before producing verdict)

Before producing a verdict, check for contradictions between Phase 2 and Phase 3.

**Contradiction pattern:** Phase 2 tests show PASS for a criterion, but Phase 3 evidence
shows a 404 page, login page, or error screenshot for the same criterion.

**When a contradiction is detected, the orchestrator MUST resolve it before issuing a verdict:**

1. Re-take a fresh authenticated screenshot of the disputed URL:
   ```bash
   npx tsx ~/.claude/skills/playwright/screenshot.ts \
     '{"url": "<disputed_url>", "outputPath": "/tmp/verify-$ARGUMENTS.issue-fresh.png",
       "auth": {"env": "dev", "role": "org_admin"}}'
   ```
   Note: `"auth"` MUST be nested — `{"auth": {"env": "dev", "role": "org_admin"}}`.
   Passing `role` at the top level silently redirects to the login page.

2. Read the page heading from the fresh screenshot to determine what actually rendered:
   ```bash
   npx tsx ~/.claude/skills/playwright/extract-text.ts \
     '{"url": "<disputed_url>", "selector": "h1",
       "auth": {"env": "dev", "role": "org_admin"}}' 2>/dev/null || \
   # Fallback: describe the screenshot content visually
   echo "Read the screenshot to determine page title and content"
   ```

3. Resolve based on what the fresh evidence shows:
   - `h1` matches the expected feature content → **Mislabeled evidence.** Phase 3 agents
     mislabeled the filename (e.g., named it "404-page.png" when it captured the correct
     page). Tests were correct; treat criterion as PASS.
   - `h1` shows "404", "Not Found", or "Page Not Found" → **Real failure.** Set verdict
     to `TRANSITION_TODO`. Root cause: route or resource is missing.
   - Screenshot shows a login/auth page → **Auth schema error.** The Phase 3 skill call
     used wrong auth schema. Retry with the correct nested schema (Step 1 above) before
     concluding. Do NOT mark as FAIL without retrying with correct auth.

4. If still unresolvable after fresh screenshot and auth retry:
   - Set verdict to `NEEDS_HUMAN` — do NOT use `TRANSITION_DONE`
   - Log: "CONTRADICTION_UNRESOLVED: Phase 2 shows PASS but Phase 3 evidence is ambiguous"

**Prohibited resolutions:**
- Do NOT compare file sizes to determine whether screenshots are "the same" — file size
  is not a distinguishing signal (different pages can produce similar file sizes)
- Do NOT assume mislabeling without verifying via fresh screenshot
- Do NOT override NEEDS_HUMAN by rationalizing the contradiction

Log the contradiction in the validation report with the fresh evidence filename and resolution.
Set `contradiction_detected: true` in the Phase 6 episode storage.

5. Produce a verdict:
   - playwright_blocker or test_criteria_blocker → `TRANSITION_TODO` (hard gate, no exceptions)
   - All criteria PASS (contradictions resolved) → `TRANSITION_DONE`
   - Any criteria FAIL (real regression confirmed) → `TRANSITION_TODO`
   - Ambiguous or pre-existing issue → `NEEDS_HUMAN`
6. Write the full validation report to `/tmp/validate-$ARGUMENTS.issue-report.md`:
   ```markdown
   ## Validation Report: $ARGUMENTS.issue

   **Date:** <today>
   **Repo:** <repo>
   **Verdict:** PASS | FAIL | NEEDS_HUMAN

   ### Criteria Results

   | Criterion | Status | Evidence |
   |-----------|--------|----------|
   | <criterion> | PASS/FAIL | <evidence summary> |

   ### Evidence Artifacts
   <list from evidence manifest>

   ### Recommendation
   <TRANSITION_DONE | TRANSITION_TODO | NEEDS_HUMAN with rationale>
   ```

Save checkpoint:
```bash
python3 ~/.claude/hooks/checkpoint.py save $ARGUMENTS.issue val.phase4-complete '{"status":"evaluated","recommendation":"<verdict>","passed":<N>,"failed":<M>}'
```

---

## Phase 5: Transition Jira (INLINE — Opus)

This runs inline on Opus. Do NOT dispatch.

Based on the verdict from Phase 4:

### If TRANSITION_DONE:
1. Post validation report as Jira comment:
   ```bash
   report=$(cat /tmp/validate-$ARGUMENTS.issue-report.md)
   npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.issue", "body": "<report>"}'
   ```

**Evidence gate (MANDATORY before transition):** Verify the report was actually posted before
transitioning. This guards against silent Jira API failures:

```bash
# Verify Validation Report exists in Jira comments before transitioning to Done
_comments=$(npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "comment"}')
_has_report=$(echo "$_comments" | jq -r '[.fields.comment.comments[] | select(.body | contains("## Validation Report"))] | length')
if [ "$_has_report" = "0" ]; then
  echo "BLOCKED: Cannot transition to Done — Validation Report was not found in Jira comments."
  echo "The add_comment call may have failed silently. Re-run /validate to retry."
  exit 1
fi
```

2. Transition to Done:
   ```bash
   npx tsx ~/.claude/skills/issues/list_transitions.ts '{"issue_key": "$ARGUMENTS.issue"}'
   npx tsx ~/.claude/skills/issues/transition_issue.ts '{"issue_key": "$ARGUMENTS.issue", "transition_id": "<done-id>"}'
   ```
3. Update labels (read-then-write pattern):
   ```bash
   # 1. Fetch current labels
   current=$(npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "labels"}')
   # 2. Compute desired set: remove step:validating, add outcome:validated
   # 3. Write the full array
   npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "$ARGUMENTS.issue", "labels": [<full computed array>]}'
   ```
4. Update smoke baseline (preserves passing state for future regression detection):
   ```bash
   if [ -f /tmp/smoke-$ARGUMENTS.issue.json ]; then
     npx tsx ~/.claude/skills/agentdb/pattern_store.ts \
       "{\"task_type\": \"smoke-baseline-lambda-functions-dev\", \
         \"approach\": $(cat /tmp/smoke-$ARGUMENTS.issue.json | jq -c . 2>/dev/null || echo 'null'), \
         \"success_rate\": 1.0}" 2>/dev/null || true
   fi
   ```

### If TRANSITION_TODO:
1. Post validation report as Jira comment
2. Transition back to To Do
3. Update labels (read-then-write): remove `step:validating`, add `outcome:validation-failed`

### If NEEDS_HUMAN:
1. Post validation report as Jira comment
2. Do NOT transition
3. Update labels (read-then-write): add `outcome:needs-human`
4. Report to user that manual review is needed

**Verification (MANDATORY):** After transitioning, verify the status actually changed:
```bash
issue=$(npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "status"}')
status=$(echo "$issue" | jq -r '.fields.status.name')
```

If status didn't change, retry the transition once.

---

## Phase 6: Cost Capture and Episode Storage

### 6a: Store reflexion episode

Include validation-specific fields in the trajectory:
- `deploy_verified`: true/false
- `evidence_quality`: STRONG/SUFFICIENT/INSUFFICIENT
- `contradiction_detected`: true/false
- `verdict`: the final verdict
- `duration_seconds`: elapsed time

```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts "{\"session_id\": \"${TENANT_NAMESPACE}\", \"task\": \"/validate $ARGUMENTS.issue\", \"input\": {}, \"output\": \"<recommendation>\", \"reward\": <score>, \"success\": <true|false>, \"critique\": \"<key lesson>\", \"trajectory\": {\"deploy_verified\": <true|false>, \"evidence_quality\": \"<STRONG|SUFFICIENT|INSUFFICIENT>\", \"contradiction_detected\": <true|false>, \"verdict\": \"<verdict>\", \"duration_seconds\": <N>}}"
```

**Reward scoring (updated):**
- `1.0` — Clean pass with runtime evidence and deploy verified
- `0.8` — Passed with caveats or evidence quality only SUFFICIENT
- `0.6` — NEEDS_DEPLOY (code correct but not deployed)
- `0.4` — Failed validation, sent back to dev
- `0.2` — Escalated to human or contradiction detected

### 6b: Capture session cost
```bash
python3 ${PROJECT_ROOT}/agents/scripts/capture_session_cost.py "$ARGUMENTS.issue" "validate" --json 2>/dev/null || true
```

### 6c: Cleanup
```bash
/reclaim
```

---

## Phase 7: Print Summary

```
## Validation Complete: $ARGUMENTS.issue

| Phase | Result | Notes |
|-------|--------|-------|
| Deploy Check | <DEPLOYED/FAILED> | <repo, pipeline, build> |
| Run Tests | <N passed, M failed> | <test type> |
| Evidence | <N artifacts> | <types collected> |
| Evaluation | <PASS/FAIL/PARTIAL> | <criteria summary> |
| Transition | <DONE/TODO/NEEDS_HUMAN> | <new status> |

### Key Lesson
<One sentence: what worked, what broke, what the local model missed>
```

---

## Sub-Commands Reference

| Command | Purpose | Runs On |
|---------|---------|---------|
| `/validate-deploy-status` | Check CI passed + code deployed | Local (dispatched) |
| `/validate-run-tests` | Execute Playwright/API tests | Local (dispatched) |
| Phase 2.75 (inline) | Auth quality gate — catch local model auth failures | Opus (inline) |
| `/validate-collect-evidence` | Screenshots, logs, API responses | Local (dispatched) |
| `/validate-evaluate` | Compare results vs criteria, verdict | Opus (inline) |
| `/validate-transition` | Update Jira status | Opus (inline) |

---

## Workflow Diagram

```
/validate <issue> (this orchestrator)
  │
  ├─► Phase 0.75: Check for code review blockers (inline Opus, ~100 tokens)
  │     └─ Most recent review = REQUIRES REWORK → short-circuit to TRANSITION_TODO
  │
  ├─► Phase 0.5: Classify validation type (inline Opus, ~200 tokens)
  │     ├─ deploy-strategy: none → FAST PATH (Phase 1F)
  │     ├─ validation-type: pipeline-verification → PIPELINE PATH (Phase 1P)
  │     └─ deploy-strategy: concourse/manual + runtime → FULL PATH (Phase 1)
  │
  ├─► Phase 0.6: Visual impact classification (inline Opus, ~150 tokens)
  │     ├─ Read issue description/AC → derive has_visual_effects + ui_paths
  │     └─ Save to checkpoint (dispatch-local.py reads this for Phases 2+3 enrichment)
  │
  │  ┌─ FAST PATH ──────────────────────────────────────┐
  │  │ Phase 1F: File verification (inline Opus)        │
  │  │   ├─ Verify PR merged                            │
  │  │   ├─ Run AC checks (grep, jq, CLI commands)      │
  │  │   └─ Capture evidence → skip to Phase 4          │
  │  └──────────────────────────────────────────────────┘
  │
  │  ┌─ PIPELINE PATH ────────────────────────────────────┐
  │  │ Phase 1: /validate-deploy-status (local)          │
  │  │ Phase 1P: Read source from Bitbucket (inline Opus)│
  │  │   ├─ Verify AC against actual code + test files   │
  │  │   └─ Capture evidence → skip to Phase 4           │
  │  └──────────────────────────────────────────────────-┘
  │
  │  ┌─ FULL PATH ──────────────────────────────────────┐
  │  │ Phase 1: /validate-deploy-status (local)         │
  │  │   ├─ DEPLOYED → Phase 2                          │
  │  │   ├─ NEEDS_DEPLOY → Phase 4 (pre-set verdict)   │
  │  │   ├─ FAILED → stop                               │
  │  │   └─ IN_PROGRESS → poll 60s x10, checkpoint if exhausted │
  │  │ Phase 2: /validate-run-tests (local)             │
  │  │ Phase 2.75: Auth quality gate (inline Opus)     │
  │  │   ├─ AUTH_STATUS=AUTHENTICATED → Phase 3        │
  │  │   └─ AUTH_STATUS=AUTH_FAILED → Opus re-runs SRP │
  │  │       auth + re-tests failing criteria           │
  │  │ Phase 3: /validate-collect-evidence (local)      │
  │  └──────────────────────────────────────────────────┘
  │
  ├─► Phase 4: Evaluate results (inline Opus)
  │     ├─ Contradiction detection
  │     └─ Verdict: TRANSITION_DONE | TRANSITION_TODO | NEEDS_DEPLOY | NEEDS_HUMAN
  │
  ├─► Phase 5: Transition Jira (inline Opus)
  │
  └─► Phase 6: Cost capture + episode storage + /reclaim
```

---

**START NOW: Run Phase 0, then Phase 0.75 (blocker check), then Phase 0.5 (classify), then Phase 0.6 (visual impact), then route to Phase 1F or Phase 1.**

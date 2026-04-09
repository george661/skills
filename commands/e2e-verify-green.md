<!-- MODEL_TIER: haiku -->

# /e2e-verify-green <issue-key>

Verify that the E2E spec for this issue now PASSES. This is the GREEN gate.
Frontend repos: runs against local dev server. Backend repos: runs against deployed `$E2E_BASE_URL`.

**FAIL FAST:** Required: `E2E_REPO`, `E2E_BASE_URL`, `E2E_TAG_PREFIX`, `E2E_FRONTEND_REPOS`,
`E2E_DEV_SERVER_CMD`, `E2E_DEV_SERVER_PORT`

## Step 0: Guard

**If `e2e.not-applicable: true` in checkpoint:** Print "GREEN gate skipped (not-applicable)." Stop.

## Step 1: Determine execution mode

Read `$CURRENT_REPO` from environment (set by `/work` orchestrator or `$PWD`).

**If `$CURRENT_REPO` appears in `$E2E_FRONTEND_REPOS`:**
Mode = LOCAL. baseUrl = `http://localhost:$E2E_DEV_SERVER_PORT`

**Otherwise:**
Mode = DEPLOYED. baseUrl = `$E2E_BASE_URL`

## Step 2: Start dev server (LOCAL mode only)

```bash
# Start dev server in background, capture PID
cd $PROJECT_ROOT/../$CURRENT_REPO
$E2E_DEV_SERVER_CMD &
DEV_SERVER_PID=$!

# Wait up to 60 seconds for port to be ready
timeout 60 bash -c "until curl -sf http://localhost:$E2E_DEV_SERVER_PORT > /dev/null; do sleep 1; done"
if [ $? -ne 0 ]; then
  kill $DEV_SERVER_PID 2>/dev/null
  echo "GREEN GATE BLOCKED: Dev server failed to start on port $E2E_DEV_SERVER_PORT within 60s"
  exit 1
fi
```

## Step 3: Run the spec (from main branch, spec is now merged or PR exists)

The E2E spec branch `$ARGUMENTS-e2e-spec` must be checked out in `$E2E_REPO`:

```bash
cd $PROJECT_ROOT && npx tsx .claude/skills/playwright/run-e2e-issue.ts '{
  "issueKey": "$ARGUMENTS",
  "baseUrl": "<resolved baseUrl>",
  "outputDir": "/tmp",
  "tagPrefix": "$E2E_TAG_PREFIX",
  "e2eRepoDir": "$PROJECT_ROOT/../$E2E_REPO"
}'
```

## Step 4: Stop dev server (LOCAL mode only)

```bash
kill $DEV_SERVER_PID 2>/dev/null
```

## Step 5: Interpret results

Run `/e2e-interpret $ARGUMENTS`.

## Step 6: Hard gate

**If `ZERO_MATCH: true`:**
BLOCK with same message as `/e2e-verify-red` zero-match case.

**If `E2E_VERDICT: FAIL` or partial pass:**
BLOCK with message:
```
GREEN GATE BLOCKED: Tests still FAIL after implementation.
Failing tests:
  <FAILING_TESTS from verdict>
Artifacts:
  <ARTIFACTS from verdict>
Fix the implementation and re-run /e2e-verify-green. Do NOT create a PR until this passes.
```

**If `E2E_VERDICT: PASS`:**
- Write to checkpoint: `e2e.green-verified: true`
- Promote draft E2E PR from draft to ready-for-review:
  Use `bitbucket/update_pull_request.ts` or equivalent to set `draft: false`.
- Print:
```
GREEN confirmed for $ARGUMENTS. Both viewports pass.
E2E draft PR promoted to ready-for-review.
Feature PR may now be created.
Merge order: (1) feature PR, (2) E2E PR after feature deployed.
```

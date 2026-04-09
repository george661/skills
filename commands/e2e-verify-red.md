<!-- MODEL_TIER: haiku -->

# /e2e-verify-red <issue-key>

Verify that the E2E spec for this issue currently FAILS. This is the RED gate — no code
should be written until the test is confirmed to fail against the live environment.

**FAIL FAST:** Required variables: `E2E_REPO`, `E2E_BASE_URL`, `E2E_TAG_PREFIX`, `E2E_TEST_DATA_REPO`

## Step 0: Guards

**If checkpoint contains `e2e.not-applicable: true`:**
Print: "Issue $ARGUMENTS has no E2E spec (not-applicable). RED gate skipped." Stop.

**If checkpoint has neither `e2e.not-applicable` nor `e2e.spec-path`:**
Call `/e2e-write $ARGUMENTS` first, then continue.

## Step 1: Resolve E2E repo worktree

The spec is on the `$ARGUMENTS-e2e-spec` branch in `$E2E_REPO`, not on main.
Use `$PROJECT_ROOT/../$E2E_REPO` as the working directory.
Checkout (or confirm active branch) `$ARGUMENTS-e2e-spec`:

```bash
cd $PROJECT_ROOT/../$E2E_REPO
git checkout $ARGUMENTS-e2e-spec
```

## Step 2: Run the spec

```bash
cd $PROJECT_ROOT && npx tsx .claude/skills/playwright/run-e2e-issue.ts '{
  "issueKey": "$ARGUMENTS",
  "baseUrl": "$E2E_BASE_URL",
  "outputDir": "/tmp",
  "tagPrefix": "$E2E_TAG_PREFIX",
  "e2eRepoDir": "$PROJECT_ROOT/../$E2E_REPO"
}'
```

## Step 3: Interpret results

Run `/e2e-interpret $ARGUMENTS` to parse the result file.

## Step 4: Hard gate

**If `ZERO_MATCH: true`:**
BLOCK with message:
```
RED GATE BLOCKED: No tests matched tag $E2E_TAG_PREFIX-$ARGUMENTS.
Verify:
  1. Spec file exists at $E2E_TEST_DIR/issues/$ARGUMENTS.spec.ts in branch $ARGUMENTS-e2e-spec
  2. Tag in spec matches: '@$ARGUMENTS' (check describe and test annotations)
  3. E2E_TAG_PREFIX is set correctly (current value: $E2E_TAG_PREFIX)
```

**If `E2E_VERDICT: PASS`:**
BLOCK with message:
```
RED GATE BLOCKED: Tests PASS before implementation — spec is testing pre-existing behavior.
Strengthen assertions to target the specific NEW behavior this issue introduces.
Failing to do so means GREEN gate will pass trivially and provide no real signal.
```

**If `E2E_VERDICT: FAIL` (all tests fail):**
Write to checkpoint: `e2e.red-verified: true`
Print: "RED confirmed for $ARGUMENTS. Both viewports fail as expected. Implementation may begin."

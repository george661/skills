<!-- MODEL_TIER: haiku -->

# /e2e-interpret <issue-key>

Parse the JSON result file produced by `run-e2e-issue.ts` for the given issue key and emit a
structured verdict block. This command does NOT read screenshot images or trace files — it
parses JSON structure only. Image/trace content inspection is the caller's responsibility.

**FAIL FAST:** If any required environment variable is unset, print an error and stop.

```
Required: E2E_TAG_PREFIX
```

## Step 1: Locate result file

Read `/tmp/e2e-$ARGUMENTS-result.json`.

If the file does not exist: output `E2E_VERDICT: BLOCKED — result file not found at /tmp/e2e-$ARGUMENTS-result.json. Run run-e2e-issue.ts first.` and stop.

## Step 2: Parse and emit verdict

Read the JSON. Extract:
- `chromium.passed`, `chromium.failed`, `chromium.tests[*].title`
- `webkit.passed`, `webkit.failed`, `webkit.tests[*].title`
- `artifacts[*].type`, `artifacts[*].viewport`, `artifacts[*].path`, `artifacts[*].testTitle`
- `overallPassed`
- `zeroMatch`

Emit this exact block (fill in values):

```
E2E_VERDICT: <PASS|FAIL|BLOCKED>
CHROMIUM_DESKTOP: <PASS|FAIL>  (<N> passed, <M> failed)
WEBKIT_MOBILE: <PASS|FAIL>  (<N> passed, <M> failed)
ZERO_MATCH: <true|false>
FAILING_TESTS:
  - chromium: <test title>   (or "none")
  - webkit: <test title>     (or "none")
ARTIFACTS:
  - screenshot: /tmp/...  [chromium, <test title>]
  - trace: /tmp/...  [webkit, <test title>]
  (or "none")
RUNTIME_ANNOTATIONS:
  - issue: $ARGUMENTS
  - jira: $E2E_JIRA_BASE_URL/browse/$ARGUMENTS
```

**Verdict rules:**
- `zeroMatch: true` → `E2E_VERDICT: BLOCKED` (zero tests matched is never a pass)
- `overallPassed: true` AND both viewports have failed=0 → `E2E_VERDICT: PASS`
- Any failed > 0 in either viewport → `E2E_VERDICT: FAIL`
- Partial pass (one viewport pass, one fail) → `E2E_VERDICT: FAIL`

## Step 3: Done

The verdict block above is consumed by `/e2e-verify-red`, `/e2e-verify-green`, `/validate-evaluate`,
and `/epic-manager` orchestrator. Do not add interpretation beyond what is stated here.

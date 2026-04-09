<!-- MODEL_TIER: opus -->
<!-- INLINE: This sub-command runs inline within the /validate orchestrator. -->
<!-- This file is reference documentation — it is NOT dispatched via dispatch-local.sh. -->
---
description: Evaluate validation results against stored criteria and produce verdict
arguments:
  - name: issue
    description: Jira issue key (e.g., PROJ-123)
    required: true
  - name: test_results_path
    description: Path to test results file (default /tmp/validate-<issue>-test-results.txt)
    required: false
  - name: evidence_path
    description: Path to evidence manifest file (default /tmp/validate-<issue>-evidence.txt)
    required: false
---

# Evaluate Validation Results: $ARGUMENTS.issue

## Purpose

Compare test results and evidence against the stored validation criteria.
Produce a PASS/FAIL verdict with rationale for each criterion.
This runs **inline on Opus** within the `/validate` orchestrator — do not dispatch to local.

## Phase 1: Load Criteria

1. Fetch the validation criteria from the Jira issue:
   ```bash
   npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "description,comment"}'
   ```

2. Parse each criterion into a checklist.

## Phase 2: Load Test Results and Evidence

1. Read test results from file path (argument or default):
   ```bash
   cat /tmp/validate-$ARGUMENTS.issue-test-results.txt
   ```

2. Read evidence manifest from file path (argument or default):
   ```bash
   cat /tmp/validate-$ARGUMENTS.issue-evidence.txt
   ```

## Phase 2.5: Contradiction Detection

Before matching criteria, check for contradictions between sub-command outputs:

1. **Deploy status**: If DEPLOY_STATUS was `NEEDS_DEPLOY` or `FAILED`, flag `deploy_blocker = true`
2. **Evidence quality**: If EVIDENCE_QUALITY is `INSUFFICIENT`, flag `evidence_blocker = true`
3. **Test results**: If any test FAILED with no explanation, flag `test_blocker = true`

**If any blocker is true:**
- Log: `CONTRADICTION_DETECTED: true` with the specific blockers
- Include the blocker reason in the verdict rationale
- `TRANSITION_DONE` should not be used when blockers exist — prefer `NEEDS_DEPLOY`, `NEEDS_HUMAN`, or `TRANSITION_TODO` as appropriate

This is a soft gate for MOST repos: use judgment when evidence is INSUFFICIENT for legitimate
reasons (env down, tool unavailable). However, the following are HARD blockers that CANNOT
be overridden:
- If code_repo is e2e-tests AND any Playwright test FAILED → TRANSITION_TODO (no exceptions)
- If any acceptance criterion explicitly requires "tests run without errors" and tests have
  errors → TRANSITION_TODO (no exceptions)

Test failures in e2e-tests are NEVER infrastructure issues — they are test failures. Do NOT
create "test infrastructure" tickets to dismiss them.

For other repos, if the code review is conclusive and the reason for missing runtime evidence
is documented, `TRANSITION_DONE` is still possible with an explicit override note in the rationale.

## Phase 2.6: Playwright Test Failure Hard Gate

If code_repo is e2e-tests:
1. Parse test results for any Playwright test with STATUS: FAIL
2. If ANY Playwright test failed: set `playwright_blocker = true`
3. This blocker CANNOT be overridden by judgment, caveats, or infrastructure exemptions

Additionally, for ANY repo:
1. Parse acceptance criteria for phrases like "tests run without errors", "tests pass",
   "no test failures", "all tests pass"
2. If such criteria exist AND test results show errors/failures: set `test_criteria_blocker = true`
3. This blocker CANNOT be overridden

## Phase 2.7: Evidence Completeness Gate

Before producing a verdict, verify evidence was actually collected:

1. Read the EVIDENCE_START...EVIDENCE_END block from /validate-collect-evidence output
2. Check ARTIFACT_COUNT > 0
3. Check RUNTIME_EVIDENCE_COUNT > 0
4. If EVIDENCE_QUALITY is INSUFFICIENT: set `evidence_blocker = true`

Evidence completeness rules by repo type (from VALIDATION.md):
- UI repos (frontend-app, dashboard): at least 1 authenticated screenshot (AUTHENTICATED: true)
- Lambda repos (lambda-functions): at least 1 API response capture
- Infra repos (core-infra, auth-service, bootstrap): at least 1 terraform plan or resource state
- All repos: RUNTIME_EVIDENCE_COUNT must be > 0

If evidence_blocker is true:
```
OVERALL: FAIL
CONTRADICTION_DETECTED: true
EVIDENCE_BLOCKER: Missing required runtime evidence
RECOMMENDATION: TRANSITION_TODO
RATIONALE: Validation cannot pass without runtime evidence artifacts.
```

---

## Phase 3: Match Results to Criteria

For each validation criterion:
1. Find the matching test result from the test results file
2. Find any supporting evidence from the evidence manifest
3. Determine: does the evidence support PASS or FAIL?

## Phase 4: Produce Verdict

Write verdict to `/tmp/validate-$ARGUMENTS.issue-verdict.txt` AND print to stdout:

```
VALIDATION_VERDICT_START
ISSUE: $ARGUMENTS.issue
OVERALL: PASS | FAIL | PARTIAL
CONTRADICTION_DETECTED: true | false
DEPLOY_VERIFIED: true | false
EVIDENCE_QUALITY: STRONG | SUFFICIENT | INSUFFICIENT

CRITERION: <criterion 1 text>
STATUS: PASS | FAIL
EVIDENCE: <what proves it>
NOTES: <any caveats>
---
CRITERION: <criterion 2 text>
STATUS: PASS | FAIL
EVIDENCE: <what proves it>
NOTES: <any caveats>
---

SUMMARY:
CRITERIA_TOTAL: <N>
CRITERIA_PASSED: <M>
CRITERIA_FAILED: <K>
RECOMMENDATION: TRANSITION_DONE | TRANSITION_TODO | NEEDS_HUMAN | NEEDS_DEPLOY
RATIONALE: <one sentence explaining the recommendation>
VALIDATION_VERDICT_END
```

**Recommendation logic:**
- playwright_blocker is true → `TRANSITION_TODO` (Playwright tests failed in e2e-tests — hard gate, no exceptions)
- test_criteria_blocker is true → `TRANSITION_TODO` (acceptance criteria require passing tests but tests have errors)
- All criteria PASS + no blockers → `TRANSITION_DONE`
- All criteria PASS but deploy_blocker is true → `NEEDS_DEPLOY`
- Any criteria FAIL → `TRANSITION_TODO`
- Cannot determine / ambiguous → `NEEDS_HUMAN`
- CONTRADICTION_DETECTED and no resolution → `NEEDS_HUMAN`

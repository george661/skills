<!-- MODEL_TIER: opus -->
<!-- DISPATCH: Spawn a Task subagent with model: "opus" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Opus. -->

---
description: Review a walking skeleton definition for end-to-end coverage, repo completeness, and E2E test readiness
arguments:
  - name: epic
    description: Jira Epic key (e.g., PROJ-123)
    required: true
---

> Tool examples: [search_issues](.claude/skills/examples/jira/search_issues.md), [get_issue](.claude/skills/examples/jira/get_issue.md)

# Review Walking Skeleton: $ARGUMENTS.epic

## Overview

Validates that a walking skeleton covers the true end-to-end path for an epic. Checks that
every affected repository is represented, the skeleton spans the full stack, E2E tests are
defined, and files/routes/endpoints are accounted for.

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 1/2] Verifying coverage...`).

1. Phase 0: Load Skeleton
2. Phase 1: Verify End-to-End Coverage
3. Phase 2: Produce Verdict

**START NOW: Begin Phase 0.**

---

## Phase 0: Load Skeleton

**[phase 0/2] Loading skeleton definition...**

1. Search for skeleton issues under this epic:
   ```bash
   npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "parent = $ARGUMENTS.epic AND labels = skeleton", "fields": ["key", "summary", "description", "status", "labels"]}'
   ```

2. If NO skeleton issues found:
   ```
   VERDICT: REJECTED
   REASON: No skeleton defined for $ARGUMENTS.epic. Run /create-skeleton $ARGUMENTS.epic first.
   ```
   STOP.

3. Read the skeleton definition document:
   ```bash
   cat ${DESIGN_DOCS_PATH}/skeletons/$ARGUMENTS.epic-skeleton.md 2>/dev/null
   ```
   If not found, reconstruct the skeleton definition from the Jira issue descriptions.

4. Fetch all child issues (skeleton and non-skeleton) for comparison:
   ```bash
   npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "parent = $ARGUMENTS.epic", "fields": ["key", "summary", "description", "status", "labels", "issuelinks"]}'
   ```

5. Read the PRP for the epic to understand full scope:
   ```bash
   npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "planned-$ARGUMENTS.epic", "k": 1}'
   ```

Store as `SKELETON_ISSUES[]`, `ALL_CHILD_ISSUES[]`, `SKELETON_DOC`, `PRP_CONTENT`.

---

## Phase 1: Verify End-to-End Coverage

**[phase 1/2] Verifying end-to-end coverage...**

### Check 1: Full Stack Span

Does the skeleton span the full stack relevant to the epic?

- If epic involves UI: is there a frontend skeleton issue (frontend-app or dashboard)?
- If epic involves API: is there a Lambda/backend skeleton issue (lambda-functions)?
- If epic involves data: is there a database/infra skeleton issue (core-infra, migrations)?
- If epic involves shared types: is there a go-common skeleton issue?
- If epic involves auth changes: is there a auth-service skeleton issue?

```
[CHECK 1] Full Stack Span: PASS/FAIL
  Frontend: {present/missing/not-applicable}
  Backend:  {present/missing/not-applicable}
  Database: {present/missing/not-applicable}
  Shared:   {present/missing/not-applicable}
  Auth:     {present/missing/not-applicable}
```

**FAIL conditions:**
- Epic requires UI changes but no frontend skeleton issue exists
- Epic requires API changes but no backend skeleton issue exists
- Single-layer skeleton for a multi-layer epic

### Check 2: Repository Coverage

Does every affected repository (from PRP or epic description) have at least one skeleton issue?

```bash
# Extract repo labels from skeleton issues
# Compare against PRP affected repos list
```

```
[CHECK 2] Repository Coverage: PASS/FAIL
  Repos in PRP: {list}
  Repos with skeleton issues: {list}
  Missing repos: {list or "none"}
```

### Check 3: File/Route/Endpoint Existence

If CGC is available, verify that identified files, routes, and endpoints either exist or are
documented as "to create" in the skeleton issue descriptions.

```
mcp__CodeGraphContext__find_code for each key file mentioned in skeleton
```

```
[CHECK 3] Structural Verification: PASS/SKIP (no CGC)
  Files verified: {count}
  Files to create: {count}
  Orphaned references: {count or "none"}
```

### Check 4: E2E Test Definition

Are E2E tests defined for the skeleton path?

- Is there a skeleton issue with `repo-e2e-tests` or `test-task` label?
- Does the skeleton doc or issue description specify a journey test file?
- Are page objects listed?
- Are test data requirements documented?

```
[CHECK 4] E2E Test Definition: PASS/FAIL
  Journey test file: {specified/missing}
  Page objects: {listed/missing}
  Test data: {documented/missing}
```

### Check 5: Dependency Links

Are non-skeleton child issues properly linked as blocked by skeleton issues?

```
[CHECK 5] Dependency Links: PASS/FAIL
  Non-skeleton issues: {count}
  Properly linked: {count}
  Missing links: {list or "none"}
```

---

## Phase 2: Produce Verdict

**[phase 2/2] Producing verdict...**

### Verdict Criteria

| Verdict | Conditions |
|---------|-----------|
| **APPROVED** | All 5 checks PASS (Check 3 may be SKIP if no CGC) |
| **NEEDS_FIXES** | 1-2 checks FAIL with identifiable gaps |
| **REJECTED** | 3+ checks FAIL, or skeleton covers only a single layer for a multi-layer epic |

### Output Format

```
## Skeleton Review: $ARGUMENTS.epic

**Verdict:** {APPROVED | NEEDS_FIXES | REJECTED}

### Coverage Summary
| Check | Result | Details |
|-------|--------|---------|
| Full Stack Span | {PASS/FAIL} | {details} |
| Repository Coverage | {PASS/FAIL} | {details} |
| Structural Verification | {PASS/SKIP} | {details} |
| E2E Test Definition | {PASS/FAIL} | {details} |
| Dependency Links | {PASS/FAIL} | {details} |

### Gaps Found (if NEEDS_FIXES or REJECTED)
1. {gap description + recommended fix}
2. {gap description + recommended fix}

### Recommendations
- {actionable recommendation}
```

If **NEEDS_FIXES**: output includes specific gaps that `/fix-skeleton` can address.
If **REJECTED**: output includes fundamental issues that require re-running `/create-skeleton`.
If **APPROVED**: skeleton is ready for implementation via `/work` on skeleton issues.

---

## Anti-Patterns

| Don't | Do Instead |
|---|---|
| Approve single-layer skeletons for multi-layer epics | Require full stack coverage |
| Skip E2E test check | Every skeleton must have E2E tests defined |
| Ignore missing dependency links | Non-skeleton issues must be blocked by skeleton |
| Pass skeletons without checking PRP alignment | Verify skeleton covers PRP scope |

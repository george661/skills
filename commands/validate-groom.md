<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Validate grooming output — ensure all PRP tasks have issues, test tasks are present, dependencies match, and design alignment is preserved
arguments:
  - name: epic
    description: Jira Epic key (e.g., PROJ-123) that has been groomed
    required: true
---

> Tool examples: [get_issue](.claude/skills/examples/jira/get_issue.md), [search_issues](.claude/skills/examples/jira/search_issues.md), [add_comment](.claude/skills/examples/jira/add_comment.md)
> Skill reference: [session-init](.claude/skills/session-init.skill.md)
> Skill reference: [review-architecture](.claude/skills/review-architecture.md)

# Validate Grooming: $ARGUMENTS.epic

## Purpose

This command rigorously evaluates the output of `/groom` to ensure:
1. All PRP implementation tasks have corresponding Jira issues
2. All test tasks (e2e-tests, lambda-functions hurl/integration, frontend-app Pact) have dedicated issues
3. All issues are correctly linked to the Epic parent
4. Dependencies between issues match the PRP dependency graph
5. Tier-based priority labels are consistent
6. Issue acceptance criteria map to PRP requirements
7. Design session alignment is preserved across all issues
8. No duplicate or orphan issues exist

**Run this AFTER `/groom` and BEFORE sprint planning.**

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/11] Running validation...`).

1. Phase 0: Initialize session and load context
2. Phase 1: Load PRP and extract expected tasks
3. Phase 2: Fetch all child issues under Epic
4. Phase 3: Validate task-to-issue coverage
5. Phase 3.5: Validate test task issue coverage
6. Phase 4: Validate parent links and dependencies
7. Phase 4.5: Validate tier-based priority alignment
8. Phase 5: Validate issue acceptance criteria
9. Phase 6: Check for duplicates, orphans, and design alignment
10. Phase 7: First Grooming Review
11. Phase 8: Architectural Review
12. Phase 9: Second Grooming Review
13. Phase 10: Generate validation report and update Epic

**START NOW: Begin Phase 0/Step 0.**

---

## Phase 0: Initialize Session

**[phase 0/13] Initializing session...**

1. Search AgentDB for prior validation context:
   ```bash
   npx tsx ~/.claude/skills/agentdb/recall_query.ts \
     '{"query": "$ARGUMENTS.epic grooming validation"}'
   ```

2. Read the Epic from Jira:
   ```bash
   npx tsx ~/.claude/skills/issues/get_issue.ts \
     '{"issue_key": "$ARGUMENTS.epic", "fields": "key,summary,description,status,labels,comment", "expand": "renderedFields"}'
   ```

3. Extract: summary, status, labels, and any "Grooming Complete" comment (look for issue index table).

---

## Phase 1: Load PRP and Extract Expected Tasks

**[phase 1/13] Loading PRP...**

1. Find the PRP from Epic Jira comments (look for "PRP Created" with a file path) or AgentDB:
   ```bash
   npx tsx ~/.claude/skills/agentdb/recall_query.ts \
     '{"key": "planned-$ARGUMENTS.epic", "namespace": "${TENANT_NAMESPACE}"}'
   ```

2. Read the PRP file:
   ```bash
   cat ${PROJECT_ROOT}/${DOCS_REPO}/PRPs/[path]/PRP-XXX-{slug}.md
   # or search:
   grep -rl "$ARGUMENTS.epic" ${PROJECT_ROOT}/${DOCS_REPO}/PRPs/ | head -3
   ```

3. If no PRP found → STOP. Report: "No PRP found for $ARGUMENTS.epic."

4. Extract from the PRP:
   - `PRP_AFFECTED_REPOS` ← `**Affects**:` field
   - `PRP_DESIGN_SESSION` ← `**Design Session**:` field
   - All `### Implementation Tasks` sections (every task per repository)
   - All `### Test Infrastructure Impact` sub-sections:
     - `e2e-tests`: journey files, page objects, test-ids listed
     - `lambda-functions`: unit tests, hurl files, integration tests listed
     - `frontend-app`: Pact contract files listed
     - Any other repo test sections
   - Expected dependency relationships between tasks

Store as:
- `EXPECTED_IMPL_TASKS[]` — implementation tasks
- `EXPECTED_TEST_TASKS{}` — keyed by type: `e2e-tests`, `lambda-functions-hurl`, `lambda-functions-integration`, `frontend-app-pact`, `other`

---

## Phase 2: Fetch All Child Issues Under Epic

**[phase 2/13] Fetching child issues...**

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts \
  '{"jql": "\parent = $ARGUMENTS.epic", "fields": ["key","summary","status","labels","priority","issuelinks","description","issuetype"]}'
```

Store all results as `ACTUAL_ISSUES[]`. Separate into:
- `IMPL_ISSUES[]` — issues without `test-task` label
- `TEST_TASK_ISSUES[]` — issues with `test-task` label

---

## Phase 3: Validate Task-to-Issue Coverage

**[phase 3/13] Checking implementation task coverage...**

For each task in `EXPECTED_IMPL_TASKS[]`, find a matching issue in `IMPL_ISSUES[]`.

Match by: summary similarity (≥80% word overlap) or explicit task title reference in description.

| Expected Task | Matched Issue | Status |
|---|---|---|
| {task title} | {issue key or MISSING} | PASS/BLOCKING |

**Flag as BLOCKING** if any implementation task has no matching issue.

### Task Type Mismatch Check

**Flag as WARNING** if any operational or research task is incorrectly typed as Story:
- Tasks with signals (`run`, `execute`, `make `, `AWS profile`, `no code changes`) should be Task, not Story
- Tasks with signals (`discovery`, `audit`, `discovery only`, `document the`, `no PR needed`) should be Task, not Story
- Only implementation tasks should be Story type
---

## Phase 3.5: Validate Test Task Issue Coverage

**[phase 3.5/13] Checking test task issue coverage...**

**This is the most frequently missing part of grooming. Validate each test type explicitly.**

### e2e-tests Test Task

**If `EXPECTED_TEST_TASKS.e2e-tests` is non-empty** (PRP named journey files, page objects, or test-ids):

- [ ] At least one issue in `TEST_TASK_ISSUES[]` has `repo-e2e-tests` label
- [ ] That issue's description references specific journey spec files from the PRP
- [ ] Run command (`npx playwright test`) is present

**BLOCKING** if e2e-tests PRP section is non-empty and no `repo-e2e-tests test-task` issue exists.

### lambda-functions Hurl Test Task

**If `EXPECTED_TEST_TASKS.lambda-functions-hurl` is non-empty** (PRP named specific hurl files):

- [ ] At least one issue in `TEST_TASK_ISSUES[]` has `repo-lambda-functions` label and references hurl
- [ ] Specific hurl file names from PRP are in the issue description
- [ ] Run command (`hurl --test`) is present

**BLOCKING** if lambda-functions hurl section is non-empty and no matching test task issue exists.

### lambda-functions Integration Test Task

**If `EXPECTED_TEST_TASKS.lambda-functions-integration` is non-empty** (PRP named integration test changes):

- [ ] At least one issue in `TEST_TASK_ISSUES[]` has `repo-lambda-functions` label and references integration tests
- [ ] Issue references `tests/integration/integration_test.go`

**BLOCKING** if lambda-functions integration section is non-empty and no matching test task issue exists.

### frontend-app Pact Test Task

**If `EXPECTED_TEST_TASKS.frontend-app-pact` is non-empty** (PRP named Pact contract files):

- [ ] At least one issue in `TEST_TASK_ISSUES[]` has `repo-frontend-app` label and references Pact
- [ ] Specific Pact contract file names from PRP are in the issue description
- [ ] `npm run test:pact` is noted as MANDATORY

**BLOCKING** if frontend-app Pact section is non-empty and no matching test task issue exists.

### Summary Table

| Test Type | PRP Non-Empty? | Issue Exists? | Status |
|---|---|---|---|
| e2e-tests Playwright | YES/NO | YES/NO | PASS/BLOCKING/N/A |
| lambda-functions hurl | YES/NO | YES/NO | PASS/BLOCKING/N/A |
| lambda-functions integration | YES/NO | YES/NO | PASS/BLOCKING/N/A |
| frontend-app Pact | YES/NO | YES/NO | PASS/BLOCKING/N/A |

---

## Phase 4: Validate Parent Links and Dependencies

**[phase 4/13] Checking parent links and dependency structure...**

For each issue in `ACTUAL_ISSUES[]`:

- [ ] Issue has `parent` set to `$ARGUMENTS.epic`
- [ ] "Blocks" links match the dependency tier ordering from PRP

Flag any issue with wrong parent as **BLOCKING**.
Flag any dependency link that inverts the expected execution order as **WARNING**.

---

## Phase 4.5: Validate Tier-Based Priority Alignment

**[phase 4.5/13] Checking tier labels and priorities...**

Check that every child issue has:
1. Exactly one `tier-N` label
2. A Jira priority that matches the tier-to-priority mapping:

| Tier | Expected Priority |
|------|-------------------|
| 1 | Highest |
| 2 | High |
| 3 | Medium |
| 4 | Low |
| 5 | Low |
| 6+ | Lowest |

**Validation checks:**
- Every issue MUST have exactly one `tier-N` label — **BLOCKING** if missing
- Priority MUST match the tier mapping above — **WARNING** if mismatched
- No issue should have a higher priority than an issue in a lower-numbered tier

---

## Phase 5: Validate Issue Acceptance Criteria

**[phase 5/13] Checking acceptance criteria quality...**

For each issue in `ACTUAL_ISSUES[]`:

- Does the description contain acceptance criteria? (not just a task title)
- Are criteria binary-testable (pass/fail)?
- Do they reference the specific PRP requirements for that task?

Flag issues with no acceptance criteria as **BLOCKING**.
Flag vague criteria ("works correctly", "is fast") as **WARNING**.

---

## Phase 6: Check for Duplicates, Orphans, and Design Alignment

**[phase 6/13] Checking for duplicates, orphans, and design alignment...**

### Duplicates

Find issues with >80% summary similarity. Flag pairs as **WARNING**.

### Orphans

Find issues linked to `$ARGUMENTS.epic` that do NOT correspond to any PRP task (including expected test tasks). Flag as **WARNING** (may be intentional additions — note but do not block).

### Design Session Alignment

If `PRP_DESIGN_SESSION` is non-empty and not "None":

Load `${DESIGN_DOCS_PATH}/sessions/{PRP_DESIGN_SESSION}/state.json`. Check:

1. **Deferred decisions respected**: Issues do NOT implement items listed in `deferred_decisions` — **BLOCKING** if violated.
2. **Design deviation annotations present**: Issues that touch areas flagged in design `interview.invariants` have the "Design Review Note" annotation in their description — **WARNING** if missing.
3. **Invariants in acceptance criteria**: Key invariants from `interview.invariants` appear in at least one issue's acceptance criteria — **WARNING** if absent.

---

## Phase 7: First Grooming Review

**[phase 7/13] First review pass...**

Read the full issue set as if picking up sprint work with zero additional context:

- Is the execution order clear from tier labels and priority?
- Can each issue be completed independently within its tier?
- Is the test task sequence correct — do test issues come after the implementation issues they verify?
- Are there any gaps that would cause a developer to open the PRP mid-sprint?

Note findings — **BLOCKING** if gaps would prevent a sprint from running.

---

## Phase 8: Architectural Review

**[phase 8/13] Architectural review...**

- Does the issue breakdown match the bounded context boundaries in the CML domain model?
- Are cross-repository synchronization issues present where needed (type changes, API contracts)?
- Are any issues too large to complete in a single work session? (Flag for split)
- Does the dependency ordering prevent parallel work that could be parallelized?

---

## Phase 9: Second Grooming Review

**[phase 9/13] Final review pass...**

With all prior findings in mind, confirm:

- All BLOCKING issues from Phases 3–8 are documented
- Test task coverage is complete
- Tier/priority alignment is correct
- The issue set is coherent and sprint-ready

---

## Phase 10: Generate Validation Report and Update Epic

**[phase 10/13] Generating report...**

### 10.1 Produce Validation Report

```markdown
## Grooming Validation Report: $ARGUMENTS.epic

**Groomed Epic**: {Epic summary}
**PRP**: {PRP file path}
**Design Session**: {session_id or "None"}
**Validation Date**: {today}
**Issues Found**: {N total} ({M test task issues})

### Result: PASS / FAIL

### Implementation Task Coverage
{Phase 3 table}

### Test Task Coverage
{Phase 3.5 summary table}

### Parent Links and Dependencies
{Phase 4 findings}

### Tier and Priority Alignment
{Phase 4.5 findings}

### Acceptance Criteria Quality
{Phase 5 findings}

### Design Alignment
{Phase 6 design findings}

### Architectural Concerns
{Phase 8 findings}

### Blocking Issues (must fix before sprint planning)
1. {issue}

### Warnings (should fix, not blocking)
1. {warning}

### Next Step
{If PASS}: Epic is ready for sprint planning
{If FAIL}: Run `/fix-groom $ARGUMENTS.epic`, then re-run `/validate-groom`
```

### 10.2 Post Report to Jira

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts \
  '{"issue_key": "$ARGUMENTS.epic", "body": "**Grooming Validation Report**\n\n{validation report content}"}'
```

### 10.3 Gate: Pass or Fail

- **PASS**: No blocking issues → Epic ready for sprint planning
- **FAIL**: Blocking issues exist → instruct user to run `/fix-groom $ARGUMENTS.epic`

---

## Blocking Issue Reference

| Issue Type | Blocking? |
|---|---|
| Implementation task has no matching issue | YES |
| e2e-tests PRP section non-empty but no test task issue | YES |
| lambda-functions hurl section non-empty but no test task issue | YES |
| lambda-functions integration section non-empty but no test task issue | YES |
| frontend-app Pact section non-empty but no test task issue | YES |
| Issue missing `tier-N` label | YES |
| Issue has no acceptance criteria | YES |
| Issue parent not linked to Epic | YES |
| Deferred design decision included in issue scope | YES |
| Priority mismatches tier mapping | WARNING |
| Vague acceptance criteria | WARNING |
| Dependency link inverts execution order | WARNING |
| Design invariants not in any issue's acceptance criteria | WARNING |
| Orphan issues not in PRP | WARNING |
| Duplicate issue summaries | WARNING |

<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Validate a plan document for completeness, design alignment, cross-impacts, and testability before grooming
aliases: [validate-prp]
arguments:
  - name: epic
    description: Jira Epic key (e.g., PROJ-123) that has an associated plan
    required: true
---

> Tool examples: [get_issue](.claude/skills/examples/jira/get_issue.md), [search_issues](.claude/skills/examples/jira/search_issues.md), [add_comment](.claude/skills/examples/jira/add_comment.md)
> Skill reference: [session-init](.claude/skills/session-init.skill.md)
> Skill reference: [review-architecture](.claude/skills/review-architecture.md)

# Validate PRP: $ARGUMENTS.epic

## Purpose

This command rigorously evaluates a PRP document created by `/plan` to ensure:
1. All sections are complete and well-defined
2. The PRP is in alignment with any linked `/design` session outputs
3. Cross-repository impacts are identified
4. Testing strategy covers all requirements — including e2e-tests, lambda-functions hurl/integration, and frontend-app Pact
5. Dependencies are correctly mapped
6. Acceptance criteria are objectively verifiable

**Run this AFTER `/plan` and BEFORE `/groom`.**

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/13] Running validation...`).

1. Phase 0: Initialize session and load context
2. Phase 1: Locate and load PRP document
3. Phase 2: Validate PRP structure completeness
4. Phase 2.5: Design Session Alignment Check
5. Phase 3: Analyze cross-repository impacts
6. Phase 4: Validate testing strategy — e2e-tests, lambda-functions, frontend-app Pact
7. Phase 5: Verify dependency completeness
8. Phase 6: Check acceptance criteria objectivity
9. Phase 7: First PRP Review
10. Phase 8: Architectural Review
11. Phase 8.5: Security Audit
12. Phase 9: Second PRP Review
13. Phase 10: Generate validation report and update Epic

**START NOW: Begin Phase 0/Step 0.**

---

## Phase 0: Initialize Session

1. Search AgentDB for prior validation context:
   ```bash
   npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "$ARGUMENTS.epic PRP validation design session"}'
   ```

2. Read the Epic from Jira:
   ```bash
   npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.epic", "fields": "key,summary,description,status,labels,comment", "expand": "renderedFields"}'
   ```

3. Extract: summary, description, comments (find any "PRP Created" comment with a PRP path).

---

## Phase 1: Locate and Load PRP Document

1. Find the PRP from the Epic's Jira comments (look for "PRP Created" with a file path).

2. Read the PRP file:
   ```bash
   cat ${PROJECT_ROOT}/${DOCS_REPO}/PRPs/[path]/PRP-XXX-{slug}.md
   # or search:
   grep -rl "$ARGUMENTS.epic" ${PROJECT_ROOT}/${DOCS_REPO}/PRPs/ | head -3
   ```

3. If no PRP found → STOP. Report: "No PRP found for $ARGUMENTS.epic. Run `/plan` first."

4. Extract from PRP header:
   - `**Design Session**:` field → store as `PRP_DESIGN_SESSION`
   - `**Affects**:` field → store as `PRP_AFFECTED_REPOS`

---

## Phase 2: Validate PRP Structure Completeness

Check that all required sections exist and are non-empty:

| Section | Required | Notes |
|---|---|---|
| Problem Statement | YES | Must be specific, not generic |
| Functional Requirements | YES | At least one FR with MUST/SHOULD |
| Non-Functional Requirements | YES | At least one |
| Proposed Solution | YES | Technical approach per repo |
| Acceptance Criteria | YES | Per repository, binary-testable |
| Implementation Tasks | YES | Broken down by repo |
| Design Artifacts | YES | Linked session or explicit "None" note |
| Domain Model Design | YES if domain affected AND domain-index.json exists | CML changes listed or N/A |
| Test Infrastructure Impact | YES | Must have sub-sections for every affected repo |
| e2e-tests Tests sub-section | YES if e2e-tests affected | Journey files, page objects, test-ids |
| lambda-functions Tests sub-section | YES if lambda-functions affected | Unit, hurl, integration explicitly listed |
| frontend-app Tests sub-section | YES if frontend-app affected | Pact consumer contracts explicitly listed |
| Scheduled Job Verification | if applicable | If Lambdas/EventBridge involved |
| API Contract Validation | YES if API changes | |
| Related PRPs | YES | Can be "None" |
| Decision Log | YES | At least initial draft entry |
| Open Questions | YES | Can be empty list |

Flag each missing section as **BLOCKING**.

---

## Phase 2.5: Design Session Alignment Check

**[phase 2.5/13] Checking design session alignment...**

### Step 1: Locate Design Session

If `PRP_DESIGN_SESSION` is non-empty and not "None":
```bash
SESSION_PATH="${DESIGN_DOCS_PATH}/sessions/${PRP_DESIGN_SESSION}"
ls "${SESSION_PATH}/"
```

If `PRP_DESIGN_SESSION` is empty or "None":
- Search for a matching session by Epic keywords:
  ```bash
  grep -rl "$ARGUMENTS.epic" "${DESIGN_DOCS_PATH}/sessions/*/state.json" 2>/dev/null
  grep -rl "<epic-keywords>" "${DESIGN_DOCS_PATH}/sessions/*/state.json" 2>/dev/null
  ```
- If a session is found but PRP does not reference it: **BLOCKING** — "Design session {id} exists but PRP does not reference it."
- If no session found: **WARNING** (not blocking) — "No design session found."

### Step 2: Load Design Session State

Read `${SESSION_PATH}/state.json`. Extract:
- `DESIGN_STATUS` ← `overall_status`
- `DESIGN_PROBLEM` ← `interview.problem`
- `DESIGN_REPOS` ← `interview.integration_points.repositories`
- `DESIGN_API_CONTRACTS` ← `interview.integration_points.api_contracts_changed`
- `DESIGN_INVARIANTS` ← `interview.invariants`
- `DESIGN_DEFERRED` ← `deferred_decisions`
- `DESIGN_CML_CHANGES` ← `phases.domain-model.proposed_cml_changes` (if present)
- `DESIGN_WIREFRAMES` ← `phases.wireframe.outputs` (if present)
- `DESIGN_CONTRACTS` ← `phases.contract.outputs` (if present)
- Phase confidence scores from each `phases.*.confidence`

### Step 3: Validate Design Session Completeness

| Check | Pass Condition | Fail Action |
|---|---|---|
| `overall_status === "complete"` | Must be complete | BLOCKING |
| All phases `confidence >= 0.90` | Each phase ≥ 90% | BLOCKING — list phases below threshold |
| `open_questions` empty | No unresolved questions | WARNING |

If any BLOCKING issues → report and stop this phase.

### Step 4: Validate PRP Alignment with Design

#### 4a. Problem Statement Alignment
- **PASS**: PRP problem statement is substantively equivalent to `DESIGN_PROBLEM`
- **BLOCKING**: PRP contradicts or omits a key problem from the design interview

#### 4b. Repository Scope Alignment
- **PASS**: All repos in `DESIGN_REPOS` appear in PRP `**Affects**`
- **BLOCKING**: One or more repos from `DESIGN_REPOS` missing from PRP
- **WARNING**: PRP lists additional repos not in `DESIGN_REPOS`

#### 4c. Domain Changes Alignment (if domain-model phase ran)
- **SKIP** if TENANT_DOMAIN_PATH is unset or domain-index.json does not exist at that path — domain model is not configured for this project
- **PASS**: All proposed CML changes from design are accounted for in PRP
- **BLOCKING**: PRP Domain Model Design section missing or omits design changes
- **WARNING**: PRP adds domain changes not in design session

#### 4d. Invariants Reflected
- **PASS**: Each `DESIGN_INVARIANTS` item is in PRP constraints or acceptance criteria
- **BLOCKING**: One or more invariants not reflected anywhere in PRP

#### 4e. Deferred Decisions Respected
- **PASS**: Items in `DESIGN_DEFERRED` are NOT in PRP scope
- **BLOCKING**: PRP includes implementation tasks for items explicitly deferred in design

#### 4f. Wireframe Coverage (if wireframe phase ran)
- **PASS**: Each wireframed screen has at least one acceptance criterion in PRP
- **WARNING**: Wireframed screens not referenced in acceptance criteria

#### 4g. API Contract Coverage (if contract phase ran)
- **PASS**: Contract files referenced and type alignment JSON acknowledged in PRP
- **WARNING**: Contract artifacts not referenced in PRP

#### 4h. API Contracts Changed
- **PASS**: Every `DESIGN_API_CONTRACTS` entry has an implementation task and acceptance criterion
- **BLOCKING**: Changed API contracts missing from implementation tasks

### Step 5: Alignment Summary

```
## Design Session Alignment: {session_id}

| Check | Status | Notes |
|---|---|---|
| Design session complete | PASS/FAIL | {confidence scores} |
| Problem statement | PASS/FAIL/WARN | {details} |
| Repository scope | PASS/FAIL/WARN | {missing repos if any} |
| Domain changes | PASS/FAIL/WARN | {details} |
| Invariants reflected | PASS/FAIL | {missing if any} |
| Deferred decisions respected | PASS/FAIL | {violations if any} |
| Wireframe coverage | PASS/WARN | {uncovered screens if any} |
| API contract coverage | PASS/WARN | {details} |
| API contracts changed | PASS/FAIL | {missing tasks if any} |

Overall: ALIGNED / MISALIGNED (N blocking issues, M warnings)
```

If MISALIGNED with any BLOCKING issues → do not proceed to Phase 3. Recommend `/fix-prp $ARGUMENTS.epic`.

---

## Phase 3: Analyze Cross-Repository Impacts

For each repository in PRP `**Affects**`:
- Verify the implementation tasks section has tasks for that repository
- Verify the acceptance criteria section has criteria for that repository
- Flag any repository listed in Affects with no tasks or criteria as **BLOCKING**

---

## Phase 4: Validate Testing Strategy

**[phase 4/13] Validating test coverage...**

This phase specifically checks for the test suites most commonly missed.

### 4.1 Read Repo TESTING.md Files

For each affected repository, verify the PRP's Test Infrastructure Impact section was derived from that repo's actual TESTING.md (not invented). Check:
```bash
cat ${PROJECT_ROOT}{repo}/TESTING.md | head -50   # verify test types match PRP
```

### 4.2 e2e-tests Coverage Check

**If e2e-tests is in `PRP_AFFECTED_REPOS` or any UI/frontend changes are present:**

- [ ] PRP has a `### e2e-tests Tests` sub-section
- [ ] Journey spec file(s) explicitly named: `tests/journeys/{domain}.spec.ts`
- [ ] Page objects explicitly named: `pages/{PageName}.ts` or "none"
- [ ] `test-ids.ts` changes explicitly noted or "none"
- [ ] Run command present: `npx playwright test tests/journeys/{domain}.spec.ts --project=chromium`

**BLOCKING** if e2e-tests is affected and any of the above are missing or vague ("update e2e tests" without specifics).

### 4.3 lambda-functions Coverage Check

**If lambda-functions is in `PRP_AFFECTED_REPOS`:**

- [ ] Unit tests per Lambda: `functions/{name}/main_test.go` named explicitly
- [ ] Hurl smoke tests: specific file additions named (`auth-gates.hurl`, `public-endpoints.hurl`, etc.) or "none"
- [ ] Integration tests: `tests/integration/integration_test.go` changes noted or "none"
- [ ] go-common package tests: `{package}/*_test.go` named or "none"
- [ ] Run commands present for each applicable test type

**BLOCKING** if lambda-functions is affected and the hurl or integration sub-sections are absent.

### 4.4 frontend-app Pact Check

**If frontend-app is in `PRP_AFFECTED_REPOS`:**

- [ ] PRP has a `### frontend-app Tests` sub-section
- [ ] Pact consumer contracts explicitly listed: `pact/consumers/{feature}.pact.spec.ts` or "none"
- [ ] `npm run test:pact` noted as MANDATORY
- [ ] Vitest unit test changes noted

**BLOCKING** if frontend-app is affected and Pact contracts section is absent.

### 4.5 General Test Requirements

- [ ] E2E Validation section present (per PROJ-210 lesson)
- [ ] Real data validation requirement present (not just mock data)
- [ ] Test data requirements listed
- [ ] If scheduled jobs involved: verification checklist present

---

## Phase 5: Verify Dependency Completeness

- Check `**Dependencies**` field in PRP header
- For each listed dependency: verify the PRP/Epic exists
- Check `## Related PRPs` references valid PRP numbers
- Verify no circular dependencies

---

## Phase 6: Check Acceptance Criteria Objectivity

For each acceptance criterion:
- Must be binary-testable (pass/fail)
- Must not use vague terms ("fast", "good", "improved", "smooth") without a measurable threshold
- Must specify which role/system performs the check

Flag non-objective criteria as **WARNING**.

---

## Phase 7: First PRP Review

Read the PRP as if implementing it with zero context:
- Note any ambiguities or missing context
- Check implementation tasks are atomic enough for a single `/work` invocation each
- Verify no TODOs or placeholders remain in critical sections

---

## Phase 8: Architectural Review

- Does the solution follow existing project patterns (see `${PROJECT_ROOT}/${DOCS_REPO}/reference/patterns/`)?
- Are there single points of failure introduced?
- Does the solution respect bounded context boundaries per the CML domain model? (Skip this check if TENANT_DOMAIN_PATH is unset or domain-index.json does not exist)
- Are there performance concerns at scale?
- Are all cross-repository type changes synchronized (JSON tags ↔ TypeScript fields)?

---

## Phase 8.5: Security Audit

- New API endpoints: authenticated and authorized?
- New PII or sensitive data: encryption addressed?
- New DynamoDB tables/queries: covered by IAM?
- OWASP top-10 relevant to the changes?

---

## Phase 9: Second PRP Review

Final read-through with all prior findings in mind. Confirm:
- All BLOCKING issues from Phases 2–8.5 are documented
- PRP is coherent end-to-end
- Test Infrastructure Impact is complete and specific

---

## Phase 10: Generate Validation Report and Update Epic

### 10.1 Produce Validation Report

```markdown
## PRP Validation Report: $ARGUMENTS.epic

**PRP**: {PRP file path}
**Design Session**: {session_id or "None"}
**Validation Date**: {today}

### Result: PASS / FAIL

### Design Session Alignment
{alignment table from Phase 2.5}

### Structure Completeness
{missing sections if any}

### Cross-Repository Coverage
{repos with missing tasks or criteria}

### Testing Strategy
{Phase 4 results — e2e-tests, lambda-functions, frontend-app Pact}

### Acceptance Criteria Quality
{non-objective criteria}

### Architectural Concerns
{Phase 8 findings}

### Security Concerns
{Phase 8.5 findings}

### Blocking Issues (must fix before /groom)
1. {issue}

### Warnings (should fix, not blocking)
1. {warning}

### Next Step
{If PASS}: Run `/groom $ARGUMENTS.epic`
{If FAIL}: Run `/fix-prp $ARGUMENTS.epic`, then re-run `/validate-plan`
```

### 10.2 Post Report to Jira

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.epic", "body": "**PRP Validation Report**\n\n{validation report content}"}'
```

### 10.3 Gate: Pass or Fail

- **PASS**: No blocking issues, design session aligned → Epic ready for `/groom`
- **FAIL**: Blocking issues exist → do NOT transition Epic. Instruct user to run `/fix-prp`

---

## Blocking Issue Reference

| Issue Type | Blocking? |
|---|---|
| Missing required PRP section | YES |
| Design session incomplete (confidence < 90%) | YES |
| Design session exists but not referenced in PRP | YES |
| PRP repos missing repos from design session | YES |
| PRP domain changes missing design session CML changes | YES |
| Design invariants not reflected in PRP | YES |
| Deferred decisions included in PRP scope | YES |
| Changed API contracts missing from tasks | YES |
| e2e-tests affected but section missing or vague | YES |
| lambda-functions affected but hurl/integration section missing | YES |
| frontend-app affected but Pact section missing | YES |
| Repository in Affects with no tasks or criteria | YES |
| Wireframe coverage gaps | WARNING |
| Contract artifact not referenced | WARNING |
| Non-objective acceptance criteria | WARNING |
| Additional repos beyond design session | WARNING |
| No design session found | WARNING |

<!-- MODEL_TIER: opus -->
<!-- No dispatch needed - this command executes directly on the session model. -->

---
description: Plan a Jira Epic by creating a plan document. Accepts Epic key or free-text description.
arguments:
  - name: input
    description: Jira Epic key (e.g., PROJ-123) OR free-text description to create new Epic
    required: true
  - name: --team
    description: Run as agent team with parallel research, authoring, and review
    required: false
agent-invokeable: true
---

<!-- Agent Team: .claude/teams/plan.yaml -->
<!-- Agents: researcher, planner, architect, reviewer -->
<!-- Usage: /plan PROJ-123 --team -->

## Agent Team Mode

**If `--team` flag is present**, load team definition from `.claude/teams/plan.yaml` and create an agent team:

```
Create an agent team using the plan-team definition from .claude/teams/plan.yaml.

Team composition:
- researcher: Gather Epic context, search patterns, map dependencies
- author (planner agent): Create PRP document from research findings
- arch-reviewer (architect agent): Architectural review + STRIDE security audit
- quality-reviewer (reviewer agent): Two-pass quality review

Coordinate per the lead_instructions in the team definition.
Use delegate mode - focus on coordination, not implementation.
The Epic to plan is: $ARGUMENTS.input
```

**If `--team` flag is NOT present**, continue with single-session execution below.

---

> Tool examples: [get_issue](.claude/skills/examples/jira/get_issue.md), [search_issues](.claude/skills/examples/jira/search_issues.md), [add_comment](.claude/skills/examples/jira/add_comment.md), [update_issue](.claude/skills/examples/jira/update_issue.md), [list_transitions](.claude/skills/examples/jira/list_transitions.md), [transition_issue](.claude/skills/examples/jira/transition_issue.md)
> Skill reference: [session-init](.claude/skills/session-init.skill.md)
> Skill reference: [review-architecture](.claude/skills/review-architecture.md)
> Skill reference: [design-gate](.claude/skills/design/design-gate.skill.md)

## Input Detection

**Detect input type before proceeding:**

```typescript
// Regex pattern for Jira issue key (any project)
const EPIC_KEY_PATTERN = /^[A-Z]+-\d+$/;

if (EPIC_KEY_PATTERN.test("$ARGUMENTS.input")) {
  // Input is Epic key - proceed to Phase 0
  epicKey = "$ARGUMENTS.input";
} else {
  // Input is free-text - trigger Epic creation flow
  freeTextDescription = "$ARGUMENTS.input";
  // Proceed to Brainstorm Phase
}
```

---

## Brainstorm Phase (Free-Text Input Only)

**If input is free-text, execute brainstorming before Epic creation:**

### B.1 Divergent Exploration

```typescript
Task tool:
  subagent_type: "researcher"
  prompt: `
    Brainstorm approaches for the following request:

    **User Request:** $ARGUMENTS.input

    **Divergent Thinking:**
    1. Generate 3-5 different approaches to solve this
    2. For each approach, identify:
       - Key benefits
       - Potential challenges
       - Affected repositories
       - Dependencies
    3. Consider edge cases and alternatives

    **Output:** List of approaches with trade-offs
  `
```

### B.2 Convergent Analysis

```typescript
Task tool:
  subagent_type: "analyst"
  prompt: `
    Analyze the brainstormed approaches and recommend the best one.

    **Approaches:** [Insert from B.1]

    **Evaluation Criteria:**
    - Alignment with existing architecture
    - Implementation complexity
    - Risk assessment
    - Dependency impact

    **Output:**
    - Recommended approach with rationale
    - Epic title suggestion
    - Epic description draft
    - Affected repositories
  `
```

### B.3 Create Epic from Free-Text

```bash
npx tsx ~/.claude/skills/issues/create_issue.ts '{
  "project": "${TENANT_PROJECT}",
  "issuetype": "Epic",
  "summary": "[Generated title from brainstorm]",
  "description": "[Generated description from brainstorm]",
  "labels": ["source:brainstorm", "step:planning"]
}'

# Store the created Epic key for subsequent phases
epicKey = [created Epic key]
```

### B.4 Continue to Phase 0

**After Epic creation, proceed with standard planning flow using the new Epic key.**

---

# Plan Jira Epic: $ARGUMENTS.input

## Prerequisites

**This command requires an Epic.** If the issue is not an Epic, convert it first in Jira UI.

## MANDATORY: Create Phase TodoWrite Items

**BEFORE doing anything else**, create these TodoWrite items:

```typescript
TodoWrite({
  todos: [
    { content: "Phase 0: Initialize session — AgentDB patterns + step label", status: "pending", activeForm: "Initializing session" },
    { content: "Phase 0.5: Design Artifact Discovery", status: "pending", activeForm: "Discovering design sessions" },
    { content: "Phase 1: Fetch Epic details and validate type", status: "pending", activeForm: "Fetching Epic details" },
    { content: "Phase 1.5: Domain Model Design — propose CML changes", status: "pending", activeForm: "Designing domain model changes" },
    { content: "Phase 1.7: Read repository CLAUDE.md, TESTING.md, VALIDATION.md for all affected repos", status: "pending", activeForm: "Reading repo test requirements" },
    { content: "Phase 2: Create PRP document (draft)", status: "pending", activeForm: "Creating PRP document" },
    { content: "Phase 2.5: Design Reference Integration", status: "pending", activeForm: "Integrating design artifacts" },
    { content: "Phase 2.7: Feature Flag and Visual Mockup prompts", status: "pending", activeForm: "Feature flag and mockup decisions" },
    { content: "Phase 2.8: Walking Skeleton Definition", status: "pending", activeForm: "Defining walking skeleton" },
    { content: "Phase 3: First PRP Review — completeness and clarity", status: "pending", activeForm: "Reviewing PRP (first pass)" },
    { content: "Phase 4: Architectural Review — project alignment", status: "pending", activeForm: "Reviewing architecture" },
    { content: "Phase 5: Security Audit", status: "pending", activeForm: "Security audit" },
    { content: "Phase 6: Second PRP Review — final validation", status: "pending", activeForm: "Reviewing PRP (second pass)" },
    { content: "Phase 7: Commit PRP + link to Epic in Jira", status: "pending", activeForm: "Linking PRP to Epic" },
    { content: "Phase 8: Analyze epic dependencies for sequencing", status: "pending", activeForm: "Analyzing dependencies" },
    { content: "Phase 9: Transition Epic to GROOMING and set step label", status: "pending", activeForm: "Transitioning Epic" },
    { content: "Phase 10: Report performance metrics + auto-validate", status: "pending", activeForm: "Reporting metrics" }
  ]
})
```

---

## Phase Gates (CANNOT PROCEED WITHOUT)

| From | To | Gate Requirement |
|------|-----|------------------|
| 0 | 0.5 | Session initialized, AgentDB searched, step label set |
| 0.5 | 1 | Design session discovery complete (linked or explicitly none) |
| 1 | 1.5 | Epic details retrieved and type validated |
| 1.5 | 1.7 | Domain design proposed — CML changes documented (or TENANT_DOMAIN_PATH not set) |
| 1.7 | 2 | All affected repo CLAUDE.md, TESTING.md, VALIDATION.md read and test requirements extracted |
| 2 | 2.5 | PRP document drafted (not yet committed) |
| 2.5 | 2.7 | Design deviations checked, DesignReferenceBlock appended to PRP |
| 2.7 | 2.8 | Feature flag and mockup decisions made |
| 2.8 | 3 | Walking skeleton APPROVED or explicitly waived |
| 3 | 4 | First review PASSED |
| 4 | 5 | Architectural review PASSED |
| 5 | 6 | Security audit PASSED |
| 6 | 7 | Second review APPROVED |
| 7 | 8 | PRP committed, Jira updated with PRP link |
| 8 | 9 | Dependencies documented in PRP |
| 9 | 10 | Epic transitioned to GROOMING, step label updated |

---

## Phase 0: Initialize Session

### 0.1 Retrieve Relevant Patterns

```bash
npx tsx ~/.claude/skills/agentdb/pattern_search.ts '{
  "task": "epic planning PRP creation",
  "k": 5
}'

npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts '{
  "task": "plan $ARGUMENTS.input",
  "k": 3
}'
```

### 0.2 Load Persistent Memory

```bash
npx tsx ~/.claude/skills/agentdb/recall_query.ts '{
  "query_id": "plan-$ARGUMENTS.input",
  "query": "$ARGUMENTS.input related context prior discussions PRPs and architectural decisions"
}'
```

### 0.3 Set Step Label

```bash
npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.input", "fields": "labels"}'
# Merge with existing labels, add step:planning
npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "$ARGUMENTS.input", "labels": ["step:planning"], "notify_users": false}'
```

---

## Phase 0.5: Design Artifact Discovery

> Skill reference: [design-gate](.claude/skills/design/design-gate.skill.md)

### Step 1: Classify work type

Scan the Epic title, description, and mentioned repository names using the classification
table in `design-gate.skill.md`. Assign one of: `ui-feature`, `api-feature`,
`backend-infra`, `platform-infra`, `non-functional`. Store as `WORK_TYPE`.

### Step 2: Run discovery

If `WORK_TYPE` is `non-functional`: skip to Phase 1 immediately.

Otherwise, follow `design-gate:discover` — pass the Epic title + description as `context`
and `WORK_TYPE`. Search `$DESIGN_DOCS_PATH/sessions/*/state.json`.

### Step 3: Handle results

**Sessions found (score > 0.5):**
- Auto-select top match, print summary
- Store `session_id` as `LINKED_DESIGN_SESSION`

**Sessions found (all scores ≤ 0.5):**
- Print candidates, ask user to confirm selection or skip
- Store confirmed `session_id` as `LINKED_DESIGN_SESSION`, or set to `none`

**No sessions found — `ui-feature`, `api-feature`, or `backend-infra`:**
```
[DESIGN WARNING] No design session found for this Epic.
Work type: {WORK_TYPE}
Expected phases: {applicable phases for work type per design-gate classification table}
Consider running /design (or individual /design:* commands) before /plan to
capture architecture decisions before writing the PRP.
Continuing without design artifacts.
```

**No sessions found — `platform-infra`:**
```
[DESIGN NOTE] No design session found. Not required for platform-infra work. Continuing.
```

### Step 4: Cross-Corpus Inconsistency Check

**Skip if `WORK_TYPE` is `non-functional`.**

After single-session deviation check, scan the full PRP corpus and all design sessions for scope conflicts with the new epic:

1. Extract the new epic's affected repositories, modules, and domain areas from brainstorm or Epic description
2. Search `${PROJECT_ROOT}/${DOCS_REPO}/prps/` for existing non-Done PRPs touching the same repositories or modules:
```bash
grep -r "repository\|affects\|repo:" ${PROJECT_ROOT}/${DOCS_REPO}/prps/ --include="*.md" -l | xargs grep -l "${AFFECTED_REPOS}" 2>/dev/null
```
3. Search `${DESIGN_DOCS_PATH}/sessions/` for design sessions covering overlapping scope:
```bash
find ${DESIGN_DOCS_PATH}/sessions -name "state.json" | xargs grep -l "${AFFECTED_REPOS}" 2>/dev/null
```
4. For each conflict found, present interactively — show conflicting approaches side-by-side:

```
[CORPUS CONFLICT DETECTED]
This Epic overlaps with: {existing PRP or design session title}
Conflicting scope: {repositories/modules in common}

Existing approach: {summary from existing PRP/session}
This Epic's approach: {summary from new Epic description}

Resolution required:
  A) Accept this Epic's approach → adds [design-decision] note documenting deviation
  B) Defer to existing PRP/session → adjust this Epic's approach before proceeding
  C) Escalate → flags both with needs-human + conflict:design labels for synchronous resolution
```

5. Apply chosen resolution:
   - **A (Accept)**: Continue; add `[design-decision]: {explanation}` note to the PRP draft in Phase 2
   - **B (Defer)**: Update the Epic description or brainstorm output to align with existing approach, then continue
   - **C (Escalate)**:
     ```bash
     npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "$ARGUMENTS.input", "labels": ["needs-human", "conflict:design"], "notify_users": false}'
     # Also update the conflicting Epic:
     npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "{conflicting-epic-key}", "labels": ["needs-human", "conflict:design"], "notify_users": false}'
     ```
     STOP: "Corpus conflict escalated. Resolve conflict:design label on both Epics before retrying /plan."

**Unresolved conflicts block Phase 1.** If any conflict has no resolution, do not proceed.

**No conflicts found:** Log `[corpus-check] No conflicts detected across ${PRP_COUNT} PRPs and ${SESSION_COUNT} design sessions.` and continue to Phase 1.

---

## Phase 1: Fetch Epic Details

```bash
npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.input", "fields": "key,summary,status,description,priority,issuetype,parent,labels", "expand": "changelog,renderedFields"}'
```

**Validate Epic type:**
- Check `fields.issuetype.name` === "Epic"
- If NOT an Epic → STOP: "This command requires an Epic. Please convert the issue to an Epic first."
- If Epic is Done or Closed → STOP and notify user

**Extract:**
- Summary (title), description, priority, labels, current status, linked issues, comments

---

## Phase 1.5: Domain Model Design

> Skill reference: [domain-context](.claude/skills/domain-context.skill.md)

**Skip this phase if `TENANT_DOMAIN_PATH` is not set or the domain index does not exist.**

### 1.5.1 Load Domain Model

```bash
python3 -c "
import json, os
idx_path = os.path.join(os.environ.get('TENANT_DOMAIN_PATH',''), os.environ.get('TENANT_DOMAIN_INDEX','domain-index.json'))
idx = json.load(open(idx_path))
print(f'Domain: {idx[\"meta\"][\"domainVision\"][:100]}')
print(f'Contexts: {len(idx[\"contexts\"])}, Aggregates: {idx[\"meta\"][\"counts\"][\"aggregates\"]}')
for name, ctx in idx['contexts'].items():
    print(f'  {name} ({ctx[\"implements\"]}) - {ctx[\"vision\"][:60]}...')
"
```

### 1.5.2 Identify Affected Bounded Contexts

Map each Epic requirement to a bounded context. For each requirement:
1. Match to a bounded context by responsibility area
2. List aggregates to be modified or created
3. List commands/events to be added or changed
4. Identify CML flows that describe the expected event sequence

### 1.5.3 Propose CML Changes

```
PROPOSED CML CHANGES for $ARGUMENTS.input
==========================================

Context: {ContextName}
  NEW Aggregate: {AggregateName}
    - {field}: {Type}
  NEW Command: {CommandName} -> {EventName}
    - {param}: {Type}
  NEW Event: {EventName}
    - {field}: {Type}
  MODIFIED Aggregate: {AggregateName}
    - ADD {field}: {Type}
  NEW Flow: {FlowName}
    - step: {CommandName} -> {EventName}

ContextMap:
  NEW: {UpstreamContext} [OHS] -> {DownstreamContext} [ACL]
```

### 1.5.4 Flag Cross-Context Coordination

If the Epic spans multiple bounded contexts, document integration points and which context owns orchestration.

### 1.5.5 Validate Domain Design

- Each entity belongs to exactly one aggregate in one context
- Aggregates respect Single Responsibility Principle
- Commands and events follow CML naming conventions
- Cross-context communication uses proper patterns (OHS/ACL, Shared Kernel, etc.)
- No duplicate entity names across contexts

---

## Phase 1.7: Read Repository Test Requirements

**For every repository listed as affected by this Epic, read its CLAUDE.md, TESTING.md, and VALIDATION.md before writing the PRP.**

This phase builds `REPO_TEST_REQUIREMENTS` — the source of truth for the PRP's Test Infrastructure Impact section.

```bash
# For each affected repository {repo}:
cat ${PROJECT_ROOT}{repo}/CLAUDE.md 2>/dev/null | head -100    # constraints and patterns
cat ${PROJECT_ROOT}{repo}/TESTING.md 2>/dev/null               # test commands, frameworks, required checks
cat ${PROJECT_ROOT}{repo}/VALIDATION.md 2>/dev/null            # deployment validation criteria
```

**Extract and record for each repo:**

| Repo | Test Types | Run Commands | Pre-commit Required | Validation Criteria |
|------|-----------|--------------|---------------------|---------------------|
| {repo} | unit/integration/e2e/pact/hurl/contract | {commands from TESTING.md} | Y/N per type | {from VALIDATION.md} |

**Known repo test patterns (for reference — always superseded by the actual TESTING.md):**

| Repo | Test Types | Key Commands |
|------|-----------|--------------|
| `lambda-functions` | Go unit, Hurl smoke, integration | `make test`, `hurl --test tests/hurl/*.hurl`, `go test ./tests/integration/...` |
| `frontend-app` | Vitest unit, Pact consumer contracts | `npm test`, `npm run test:pact` (MANDATORY) |
| `e2e-tests` | Playwright journey tests, page objects | `npx playwright test tests/journeys/{domain}.spec.ts` |
| `go-common` | Go unit | `go test ./...` |
| `auth-service` | Go unit, integration | `make test` |
| `core-infra` | Terraform plan | `terraform plan` per environment |
| `sdk` | TypeScript unit, Pact consumer | `npm test`, `npm run test:pact` |

**For e2e-tests — explicitly confirm:**
- Which journey domain file(s) are affected: `tests/journeys/{domain}.spec.ts`
- Which page objects need to be added or updated: `pages/{PageName}.ts`
- Any new `data-testid` constants needed in `test-ids.ts`
- Whether a new journey domain file is needed

**For lambda-functions — explicitly confirm:**
- Which Lambda function(s) are affected: `functions/{name}/`
- Whether `tests/hurl/` needs a new `.hurl` file or additions to an existing one (auth-gates, public-endpoints, cors-preflight)
- Whether `tests/integration/integration_test.go` needs new test cases
- Whether any go-common packages are affected and need updated unit tests

**For frontend-app — explicitly confirm:**
- Whether any new API interactions require a new Pact consumer contract file: `pact/consumers/{feature}.pact.spec.ts`
- Whether existing Pact contracts in `pact/consumers/` need updating

Store all extracted requirements as `REPO_TEST_REQUIREMENTS` for use in the PRP template.

---

## Phase 2: Create PRP Document

### 2.1 Determine PRP Location

```bash
ls ${PROJECT_ROOT}/${DOCS_REPO}/PRPs/ | sort | tail -1
# Find next PRP number and appropriate subdirectory per project conventions
```

### 2.2 Feature Flag Decision

**Determine if a feature flag is needed:**

Consider using a feature flag if:
- Feature requires gradual rollout across environments
- Feature has high rollback risk
- Feature is incomplete but needs to merge to main

Do NOT use a feature flag if:
- Bug fix with no user-facing changes
- Internal refactoring
- Documentation-only changes

If a flag is needed, prompt for a descriptive flag name and store as `FEATURE_FLAG_NAME`.

### 2.3 Visual Mockup Decision

If the Epic involves UI changes, prompt: "Create a visual mockup? (Y/N)"

Create a mockup if:
- Epic involves new UI screens or major redesigns
- Stakeholders need visual preview before implementation
- Complex UI interactions need clarification

Skip if:
- Backend-only Epic
- Simple text/label changes
- Bug fixes with obvious expected behavior

### 2.4 Launch Planning Agent

```typescript
Task tool:
  subagent_type: "planner"
  model: "sonnet"
  prompt: `
    Create a comprehensive PRP document for Jira Epic $ARGUMENTS.input.

    **Issue Details:**
    [Insert issue summary and description from Phase 1]

    **Domain Model Changes (from Phase 1.5):**
    [Insert proposed CML changes]

    **Repository Test Requirements (from Phase 1.7):**
    [Insert REPO_TEST_REQUIREMENTS table]

    **Design Session:** [LINKED_DESIGN_SESSION or "None"]

    **PRP Template Structure:**

    # PRP-XXX: [Title from Issue Summary]

    **Status**: Draft
    **Created**: [Today's Date]
    **Priority**: [From Issue]
    **Type**: [Feature/Bug/Enhancement]
    **Jira Epic**: $ARGUMENTS.input
    **Dependencies**: [List other PRPs or epics that must complete first]
    **Affects**: [List repositories affected]
    **Design Session**: [LINKED_DESIGN_SESSION or "None — run /design before /plan for complex features"]
    **Feature Flag**: [FEATURE_FLAG_NAME or "None"]

    ---

    ## Design Artifacts

    [Populated by Phase 2.5 — Design Reference Integration]

    ---

    ## Domain Model Design

    **Bounded Contexts Affected:**
    - [ContextName]: [Justification from CML model]

    **Proposed CML Changes:**

    | Change Type | Context | Element | Details |
    |-------------|---------|---------|---------|
    | NEW Aggregate | [Context] | [Name] | [Fields and purpose] |
    | NEW Command | [Context] | [Name] | [Parameters, emits EventName] |
    | NEW Event | [Context] | [Name] | [Fields] |
    | MODIFIED Aggregate | [Context] | [Name] | [What changes] |

    **CML Update Required:** YES/NO

    ---

    ## Feature Flag Migration (if applicable)

    If gated behind a feature flag, include the migration and flag management details:
    - Migration file location and SQL/config format per project conventions
    - Environment defaults (dev: ON, demo: OFF, prod: OFF is typical)
    - Steps to verify flag toggle behavior

    ---

    ## Problem Statement

    [Clear problem statement with business value and user impact]

    ---

    ## Requirements

    ### Functional Requirements

    #### FR-1: [Requirement Name]
    - **MUST** [specific requirement]
    - **SHOULD** [nice to have]
    - **MAY** [optional enhancement]

    ### Non-Functional Requirements

    - **Performance**: [if applicable]
    - **Security**: [if applicable]
    - **Accessibility**: [if applicable]

    ---

    ## Proposed Solution

    ### Phase 1: [First Phase]

    **Goal**: [What this phase accomplishes]

    #### Implementation Details

    [Technical approach for each repository affected]

    ---

    ## Acceptance Criteria

    [One section per affected repository. Name each section after the repo.]

    ### [Repository Name]
    - [ ] [Specific testable criterion]
    - [ ] [Specific testable criterion]

    ### General
    - [ ] All tests pass (see Test Infrastructure Impact for commands)
    - [ ] No TypeScript compilation errors (where applicable)
    - [ ] No lint errors or warnings in modified files

    ### Feature Flag Validation (if applicable)
    - [ ] Feature functions correctly with flag enabled
    - [ ] Feature gracefully degrades when flag is disabled
    - [ ] Flag can be toggled without deployment

    ---

    ## Implementation Tasks

    **Tier 0 — Domain model (if domain changes proposed):**
    - Task 0: Update CML model with proposed domain changes (Priority: P1)
    - Task 0.1: Regenerate domain-index.json and REFERENCE.md (Priority: P1)

    [One section per affected repository.]

    **[Repository Name] tasks:**
    - Task N: [Description] (Priority: P1/P2/P3)

    ---

    ## Test Infrastructure Impact

    > **Source:** Phase 1.7 REPO_TEST_REQUIREMENTS — populated from each repo's TESTING.md and VALIDATION.md.
    > Never invent test requirements. Always derive them from the actual files read in Phase 1.7.

    [Repeat the following block for EVERY affected repository:]

    ### [Repository Name] Tests

    **Test types required** (from [repo]/TESTING.md):
    - [ ] [Test type]: [specific file or command]
    - [ ] [Test type]: [specific file or command]

    **Pre-commit required?** [Yes/No — from TESTING.md pre-commit section]

    **Validation criteria** (from [repo]/VALIDATION.md):
    - [ ] [Criterion]

    ---

    [For projects using lambda-functions, always include the following explicit sub-sections:]

    ### lambda-functions Tests

    **Unit tests** (one per Lambda function affected):
    - [ ] `functions/{name}/main_test.go` — add/update test cases for new handler logic

    **Hurl smoke tests** (`tests/hurl/`):
    - [ ] New endpoints added to auth-gates.hurl, public-endpoints.hurl, or new `{feature}.hurl` file: [list endpoints or "none"]
    - [ ] CORS preflight entries added for new routes: [list or "none"]
    - [ ] Run: `hurl --test --variable base_url=${API_BASE_URL} tests/hurl/*.hurl`

    **Integration tests** (`tests/integration/`):
    - [ ] `integration_test.go` — new test cases for end-to-end flows: [describe or "none"]
    - [ ] Run: `go test ./tests/integration/... -v`

    **go-common unit tests** (if shared packages modified):
    - [ ] `{package}/*_test.go` — unit tests for any modified package: [list or "none"]

    ---

    ### frontend-app Tests

    **Vitest unit tests:**
    - [ ] Component tests for new/modified components: [list or "none"]
    - [ ] Hook tests for new/modified hooks: [list or "none"]
    - [ ] Run: `npm test`

    **Pact consumer contracts** (`pact/consumers/`):
    - [ ] New contract file: `pact/consumers/{feature}.pact.spec.ts` — [describe interaction or "none"]
    - [ ] Updated contracts: [list existing files that need updating or "none"]
    - [ ] Run: `npm run test:pact` (MANDATORY — blocks commit if failing)

    ---

    ### e2e-tests Tests (Playwright journeys)

    > **Critical:** e2e-tests is the most frequently missed test suite. Any change to user-facing
    > behavior — new pages, new flows, changed selectors, new data-testids — MUST be reflected here.

    **Journey spec files** (`tests/journeys/`):
    - [ ] Existing journey updated: `tests/journeys/{domain}.spec.ts` — [describe changes or "none"]
    - [ ] New journey file created: `tests/journeys/{domain}.spec.ts` — [describe or "none"]

    **Page Objects** (`pages/`):
    - [ ] Existing page object updated: `pages/{PageName}.ts` — [describe changes or "none"]
    - [ ] New page object created: `pages/{PageName}.ts` — [describe or "none"]
    - [ ] Component page object: `pages/components/{ComponentName}.ts` — [describe or "none"]

    **Test IDs** (`test-ids.ts`):
    - [ ] New data-testid constants added: [list or "none"]

    **Run command:**
    - `npx playwright test tests/journeys/{domain}.spec.ts --project=chromium`

    ---

    ### Scheduled Job Verification (if applicable)
    - [ ] Lambda deployed and visible in AWS console
    - [ ] EventBridge/CloudWatch rule is ENABLED
    - [ ] Lambda has executed at least once (check CloudWatch logs)
    - [ ] Output/side effects verified

    ---

    ### Test Data Changes
    - [ ] New fixtures required: [list or "none"]
    - [ ] Seed data updates: [describe or "none"]
    - [ ] Mock endpoint updates (Mockoon/equivalent): [list affected environments or "none"]

    ---

    ## API Contract Validation (if API changes)
    - [ ] Backend response schema matches frontend TypeScript types
    - [ ] All required fields returned by API
    - [ ] Error responses handled gracefully in UI
    - [ ] OpenAPI schema updated to match implementation

    ---

    ## Related PRPs

    [List PRPs that this depends on or relates to. Can be "None".]

    ---

    ## Decision Log

    ### [Today's Date]: Initial Draft
    - Created from Jira Epic $ARGUMENTS.input

    ---

    ## Open Questions

    [List any questions that need stakeholder input. Can be empty list.]

    **IMPORTANT:**
    - Be thorough but focused
    - If a design session is linked, use it as PRIMARY source for: problem statement,
      affected repos, domain changes, invariants, deferred scope, wireframe/contract references
    - If Epic description conflicts with design session, document the conflict explicitly
    - Use REPO_TEST_REQUIREMENTS verbatim — never invent test requirements
    - e2e-tests and lambda-functions test sections are required when those repos are affected;
      they are the most commonly missed
    - Include SPECIFIC acceptance criteria that can be validated objectively
    - Break implementation into tasks that fit a single /work invocation each
  `
```

### 2.5 Write PRP Draft

```bash
# Write PRP to docs repo — DO NOT COMMIT YET (reviews happen first)
# File: ${PROJECT_ROOT}/${DOCS_REPO}/PRPs/[subdirectory per project]/PRP-XXX-{slug}.md
```

---

## Phase 2.5: Design Reference Integration

> Runs after Phase 2 (PRP drafted), before Phase 3 (first review).
> Skill reference: [design-gate](.claude/skills/design/design-gate.skill.md)

### Step 1: Check for deviations

If `LINKED_DESIGN_SESSION` is set (not `none`):

Follow `design-gate:check-deviation` — pass the full PRP draft text as `content`,
`[LINKED_DESIGN_SESSION]` as `session_ids`, and `WORK_TYPE`.

Print all `[DESIGN DEVIATION]` warnings with suggested resolutions before Phase 3.
Deviations are informational for reviewers — do not block.

### Step 2: Append Design Artifacts section to PRP

If `LINKED_DESIGN_SESSION` is set:

Follow `design-gate:extract-references` with `LINKED_DESIGN_SESSION` and `WORK_TYPE`.
Append the rendered `DesignReferenceBlock` to the PRP as the `## Design Artifacts` section
(placed after the header block and before `## Domain Model Design`).

### Step 3: No session linked

If `LINKED_DESIGN_SESSION` is `none`:

```markdown
## Design Artifacts

> No design session linked for this Epic.
> If design artifacts exist, re-run `/plan` after completing `/design` to link them.
```

---


## Phase 2.8: Walking Skeleton Definition

> Runs after PRP content is drafted (Phase 2) and design references integrated (Phase 2.5),
> because the skeleton is derived from PRP content.

### Step 1: Create Skeleton

```
Invoke /create-skeleton $ARGUMENTS.input
```

### Step 2: Review Skeleton

```
Invoke /review-skeleton $ARGUMENTS.input
```

### Step 3: Fix-Review Loop (max 2 cycles)

- If verdict is **NEEDS_FIXES**: invoke `/fix-skeleton $ARGUMENTS.input`, then re-review
- If verdict is **REJECTED** after 2 fix cycles: escalate to user:
  ```
  ESCALATION: Walking skeleton for $ARGUMENTS.input could not pass review after 2 fix cycles.
  Manual intervention required before proceeding to PRP review.
  ```
- If verdict is **APPROVED**: proceed to Phase 3

### Step 4: Gate

Phase 3 MUST NOT execute until the skeleton is APPROVED or the user explicitly waives it.

---
## Phase 3: First PRP Review — Completeness and Clarity

```typescript
Task tool:
  subagent_type: "reviewer"
  model: "sonnet"
  prompt: `
    Perform a thorough FIRST REVIEW of the PRP document for Epic $ARGUMENTS.input.

    **Review Focus Areas:**

    1. **Completeness:**
       - [ ] Problem statement clearly defined
       - [ ] All functional requirements documented (FR-*)
       - [ ] Non-functional requirements addressed
       - [ ] Acceptance criteria are specific and testable
       - [ ] Implementation tasks are actionable
       - [ ] Dependencies identified
       - [ ] Affected repositories listed

    2. **Clarity:**
       - [ ] Requirements use MUST/SHOULD/MAY correctly
       - [ ] Technical approach is unambiguous
       - [ ] Acceptance criteria are measurable (no vague terms)

    3. **PRP Structure:**
       - [ ] All required sections present and non-empty
       - [ ] Design Artifacts section present
       - [ ] Domain Model Design section present (or N/A noted)
       - [ ] Decision log initialized

    4. **Test Infrastructure Impact — CRITICAL:**
       - [ ] Section present and populated from TESTING.md/VALIDATION.md (not invented)
       - [ ] e2e-tests section: journey files, page objects, and test-ids explicitly listed if e2e-tests is affected
       - [ ] lambda-functions section: unit tests, hurl files, integration tests explicitly listed if lambda-functions is affected
       - [ ] frontend-app section: Pact consumer contract files explicitly listed if frontend-app is affected
       - [ ] Test data changes documented
       - [ ] All pre-commit required test types identified per repo

    5. **Design Alignment (if design session linked):**
       - [ ] Problem statement consistent with design session interview
       - [ ] Affected repos match design session integration_points.repositories
       - [ ] Design invariants reflected in constraints/acceptance criteria
       - [ ] Deferred design decisions NOT included in scope
       - [ ] No unacknowledged design deviations

    **Output Format:**

    ## First PRP Review: $ARGUMENTS.input

    **Review Status:** PASS | NEEDS_REVISION

    ### Completeness: [PASS/FAIL]
    ### Clarity: [PASS/FAIL]
    ### Structure: [PASS/FAIL]
    ### Test Infrastructure: [PASS/FAIL] — list any missing test sections
    ### Design Alignment: [PASS/FAIL/N/A]

    ### Required Changes (blocking):
    1. [Change]

    ### Recommendations (non-blocking):
    1. [Recommendation]
  `
```

If NEEDS_REVISION: address all required changes and re-run until PASS.

---

## Phase 4: Architectural Review — Project Alignment

> Skill reference: [review-architecture](.claude/skills/review-architecture.md)

```typescript
Task tool:
  subagent_type: "reviewer"
  model: "sonnet"
  prompt: `
    Perform an ARCHITECTURAL REVIEW of the PRP for Epic $ARGUMENTS.input.

    1. Domain boundary validation — are entities in the right bounded contexts?
    2. Repository assignment validation — are changes in the right repos?
    3. API architecture — handler patterns, data model integrity, contract correctness
    4. Frontend architecture — component patterns, state management (if applicable)
    5. Cross-repository impact — dependency analysis, integration testing requirements
    6. Security architecture — authentication, authorization, data protection
    7. Performance — any concerns at scale?

    Check for automatic rejection triggers from the review-architecture skill.
    Output the complete Architectural Review format from the skill.
  `
```

If FAIL: address all architectural concerns and re-run until PASS.

---

## Phase 5: Security Audit

```typescript
Task tool:
  subagent_type: "reviewer"
  model: "sonnet"
  prompt: `
    Perform a SECURITY AUDIT of the PRP for Epic $ARGUMENTS.input.

    STRIDE threat model:
    - Spoofing: Are new identities or auth mechanisms introduced?
    - Tampering: Can new data paths be tampered with?
    - Repudiation: Are actions logged and attributable?
    - Information Disclosure: Does anything expose sensitive data?
    - Denial of Service: Can new endpoints be abused?
    - Elevation of Privilege: Do new roles/permissions introduce escalation risks?

    Additional checks:
    - New API endpoints: authenticated and authorized?
    - New PII or sensitive data: encrypted at rest and in transit?
    - New DynamoDB tables/queries: covered by IAM?
    - OWASP top-10 relevant to the changes?

    Output: PASS with notes, or FAIL with required remediations.
  `
```

If FAIL: address security concerns and re-run until PASS.

---

## Phase 6: Second PRP Review — Final Validation

```typescript
Task tool:
  subagent_type: "reviewer"
  model: "sonnet"
  prompt: `
    Perform a FINAL SECOND REVIEW of the PRP document for Epic $ARGUMENTS.input.

    Verify:
    1. All first review feedback incorporated
    2. All architectural review feedback incorporated
    3. All security audit feedback incorporated
    4. No remaining ambiguities
    5. All acceptance criteria testable
    6. Implementation tasks have clear repo ownership
    7. Test infrastructure impact is complete — especially:
       - e2e-tests sections if e2e-tests is affected (journeys, POMs, test-ids)
       - lambda-functions sections if lambda-functions is affected (unit, hurl, integration)
       - frontend-app Pact contracts if frontend-app is affected
    8. PRP is ready for commitment and grooming

    Output:

    ## Second PRP Review (Final): $ARGUMENTS.input

    **Review Status:** APPROVED | NEEDS_REVISION

    ### First Review Feedback: [ADDRESSED/PENDING]
    ### Architectural Feedback: [ADDRESSED/PENDING]
    ### Security Feedback: [ADDRESSED/PENDING]
    ### Test Infrastructure Completeness: [COMPLETE/INCOMPLETE]
    ### Final Verdict: [APPROVED FOR COMMIT] or [remaining issues]
  `
```

If NEEDS_REVISION: address remaining issues and re-run until APPROVED.

---

## Phase 7: Commit PRP and Link to Jira

### 7.1 Commit PRP to Docs Repo

```bash
cd ${PROJECT_ROOT}/${DOCS_REPO}

git add PRPs/
# Also add mockup if generated
git add designs/mockups/ 2>/dev/null || true

git commit -m "$ARGUMENTS.input: Create PRP-XXX for [Epic summary]

- First review: PASSED
- Architectural review: PASSED
- Security audit: PASSED
- Second review: APPROVED

$ARGUMENTS.input #comment PRP created: PRP-XXX-{slug}.md"
git push origin main
```

### 7.2 Update Jira with PRP Link

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{
  "issue_key": "$ARGUMENTS.input",
  "body": "**PRP Created**\n\n**Document**: PRP-XXX-{slug}.md\n\n**Summary**:\n- Problem: [1-2 sentence summary]\n- Solution: [1-2 sentence summary]\n- Repositories: [list]\n- Dependencies: [list]\n\n**Next Steps**:\n1. `/validate-plan $ARGUMENTS.input` — validate PRP\n2. `/groom $ARGUMENTS.input` — create sub-tasks"
}'
```

---

## Phase 8: Cross-Epic Sequencing Gate

### 8.1 Query All Non-Done Epics

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${TENANT_PROJECT} AND issuetype = Epic AND status != Done ORDER BY key ASC", "max_results": 100, "fields": ["key", "summary", "status", "priority", "labels", "issuelinks", "description"]}'
```

Skip any epics with `status = Done`. Store the result as `OPEN_EPICS`.

### 8.2 Analyze Dependencies

For each open epic, apply the following inference rules to determine its relationship with the new epic (`$ARGUMENTS.input`):

**Inference rules (explicit logic — confidence scored 0.0–1.0):**

| Condition | Action | Min Confidence |
|---|---|---|
| Same affected repository AND same domain area AND new epic's work consumes outputs from existing epic | Write `is blocked by` link on new epic | 0.7 |
| Same affected repository AND same domain area AND existing epic consumes outputs from new epic | Write `blocks` link on new epic | 0.7 |
| Same repository only, no domain overlap | Add note in rationale comment only — no Jira link | N/A |
| Entirely separate repositories and domain areas | No action | N/A |

**If confidence < 0.7 for a candidate dependency:** Write `position: standalone` — do not create a Jira link.

### 8.3 Write Jira Dependency Links

For each confirmed dependency (confidence ≥ 0.7):

```bash
# Write "blocks" link: $ARGUMENTS.input blocks PROJ-XXX
curl -s -u "${JIRA_USERNAME}:${JIRA_API_TOKEN}" \
  -X POST "https://${JIRA_HOST}/rest/api/3/issueLink" \
  -H "Content-Type: application/json" \
  -d "{\"type\":{\"name\":\"Blocks\"},\"inwardIssue\":{\"key\":\"$ARGUMENTS.input\"},\"outwardIssue\":{\"key\":\"{blocked-epic-key}\"}}"

# Write "is blocked by" link: $ARGUMENTS.input is blocked by PROJ-YYY
curl -s -u "${JIRA_USERNAME}:${JIRA_API_TOKEN}" \
  -X POST "https://${JIRA_HOST}/rest/api/3/issueLink" \
  -H "Content-Type: application/json" \
  -d "{\"type\":{\"name\":\"Blocks\"},\"inwardIssue\":{\"key\":\"{blocking-epic-key}\"},\"outwardIssue\":{\"key\":\"$ARGUMENTS.input\"}}"
```

### 8.4 Write [sequence-rationale] Comment

Write a structured comment on `$ARGUMENTS.input` regardless of whether dependencies were found:

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{
  "issue_key": "$ARGUMENTS.input",
  "body": "[sequence-rationale]\nblocks: {comma-separated keys or none}\nblocked-by: {comma-separated keys or none}\nposition: {early|middle|late|standalone}\nrationale: {1-2 sentence explanation of sequencing decision}\nunblocks-count: {N}\nconfidence: {highest confidence score, e.g. 0.85}\ngenerated: {ISO timestamp}"
}'
```

**Position assignment:**
- `early` — no blockers, unblocks ≥ 1 other epic
- `late` — blocked by ≥ 1 epic
- `middle` — both blocks and is blocked by
- `standalone` — no relationships found or all confidence < 0.7

### 8.5 Gate Verification

Phase 8 is complete when:
- [ ] All non-Done epics analyzed
- [ ] Jira links written for all confirmed dependencies (confidence ≥ 0.7)
- [ ] `[sequence-rationale]` comment present on `$ARGUMENTS.input`
- [ ] If no dependencies found: `position: standalone` comment written

Phase 9 MUST NOT execute until Phase 8 is complete.

---

## Phase 9: Transition to GROOMING

```bash
npx tsx ~/.claude/skills/issues/list_transitions.ts '{"issue_key": "$ARGUMENTS.input"}'

# Remove step:planning, add outcome:success-prp-created
npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "$ARGUMENTS.input", "labels": ["outcome:success-prp-created"], "notify_users": false}'

npx tsx ~/.claude/skills/issues/transition_issue.ts '{
  "issue_key": "$ARGUMENTS.input",
  "transition_id": "<grooming-transition-id>",
  "comment": "**Planning Complete**\n\n- PRP Created: PRP-XXX\n- Reviews: PASSED (first, architectural, security, final)\n- Dependencies: Documented\n- Ready for: `/validate-plan $ARGUMENTS.input` then `/groom $ARGUMENTS.input`",
  "notify_users": false
}'
```

---

## Phase 10: Report Performance Metrics and Auto-Validate

### 10.1 Store Completion in AgentDB

```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{
  "session_id": "${TENANT_NAMESPACE}",
  "task": "planned-$ARGUMENTS.input",
  "reward": 0.9,
  "success": true,
  "metadata": {
    "prp": "PRP-XXX",
    "status": "GROOMING",
    "designSession": "'${LINKED_DESIGN_SESSION:-none}'",
    "reviews": { "first": "PASSED", "architectural": "PASSED", "security": "PASSED", "final": "APPROVED" }
  }
}'
```

### 10.2 Auto-Validate Plan

```typescript
// Invoke /validate-plan as a subagent
Task tool:
  subagent_type: "reviewer"
  prompt: `Execute /validate-plan $ARGUMENTS.input. Return the validation verdict.`
```

If validation fails, output: "Plan created but validation found issues. Run `/fix-plan $ARGUMENTS.input` to address."

---

## Completion Summary

```markdown
## Planning Complete: $ARGUMENTS.input

**PRP**: PRP-XXX-{slug}.md
**Location**: ${REPO_DOCS}/PRPs/
**Status**: GROOMING

**Artifacts created:**
- PRP document
- Design artifacts section (linked or noted as absent)
- Visual mockup (if UI feature)
- Dependency analysis

**Next Steps:**
1. `/validate-plan $ARGUMENTS.input` — validate PRP completeness and design alignment
2. `/groom $ARGUMENTS.input` — create Jira issues from PRP
3. `/work {PROJECT}-XXX` — implement Tier 1 issues
```

---

## Failure Detection and Outcome Labeling

**Failure conditions:**
- Epic is not an Epic type
- Epic is Done or Closed
- PRP document creation failed
- Any review failed after 3 attempts
- PRP commit failed
- Epic transition to GROOMING failed

**On failure:**

```bash
npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "$ARGUMENTS.input", "labels": ["step:planning", "outcome:failure-planning-incomplete"], "notify_users": false}'
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.input", "body": "**Planning Failed**\n\n**Reason**: [specific failure]\n\n**Action Required**: [what to fix before retrying /plan]"}'
```

---

## Anti-Patterns (AUTOMATIC FAILURE)

- Running on non-Epic issue type = FAILURE
- Creating PRP without reading Epic description = FAILURE
- Skipping AgentDB memory search = FAILURE
- Skipping Phase 1.7 (repository CLAUDE.md/TESTING.md/VALIDATION.md) = FAILURE
- Inventing test requirements instead of reading from TESTING.md = FAILURE
- PRP missing e2e-tests section when e2e-tests is affected = FAILURE
- PRP missing lambda-functions hurl/integration section when lambda-functions is affected = FAILURE
- PRP missing frontend-app Pact section when frontend-app is affected = FAILURE
- Committing PRP before passing all reviews = FAILURE
- Skipping first, architectural, security, or second review = FAILURE
- Not committing PRP to docs repo = FAILURE
- Leaving Epic not transitioned to GROOMING = FAILURE
- PRP without acceptance criteria = FAILURE
- PRP without implementation tasks = FAILURE
- Not documenting dependencies = FAILURE
- Not setting/clearing step labels = FAILURE
- Skipping domain model design when TENANT_DOMAIN_PATH is set AND domain-index.json exists at that path = FAILURE
- TENANT_DOMAIN_PATH is set but domain-index.json does not exist at that path = WARNING (not FAILURE)
- Design session exists but PRP does not reference it = FAILURE
- PRP contradicts design session without documenting the conflict = FAILURE
- Deferred design decisions included in PRP scope = FAILURE

---

**START NOW: Create the TodoWrite items above, then begin Phase 0.**

<!-- MODEL_TIER: opus -->
<!-- No dispatch needed - this command executes directly on the session model. -->

---
description: Groom a Jira Epic by creating issues from the PRP and transitioning to To Do
arguments:
  - name: epic
    description: Jira Epic key (e.g., PROJ-123) - must be an Epic type
    required: true
  - name: --team
    description: Run as agent team with parallel parsing, issue creation, and review
    required: false
---

<!-- Agent Team: .claude/teams/groom.yaml -->
<!-- Agents: researcher, coordinator, reviewer -->
<!-- Usage: /groom PROJ-123 --team -->

## Agent Team Mode

**If `--team` flag is present**, load team definition from `.claude/teams/groom.yaml` and create an agent team:

```
Create an agent team using the groom-team definition from .claude/teams/groom.yaml.

Team composition:
- parser (researcher agent): Extract tasks from PRP, calculate dependency tiers
- issue-creator (coordinator agent): Batch create Jira issues with links
- issue-reviewer (reviewer agent): Three-pass review (completeness, architecture, final)

Coordinate per the lead_instructions in the team definition.
Use delegate mode - focus on coordination, not implementation.
The Epic to groom is: $ARGUMENTS.epic
```

**If `--team` flag is NOT present**, continue with single-session execution below.

---

> Tool examples: [get_issue](.claude/skills/examples/jira/get_issue.md), [search_issues](.claude/skills/examples/jira/search_issues.md), [create_issue](.claude/skills/examples/jira/create_issue.md), [update_issue](.claude/skills/examples/jira/update_issue.md), [add_comment](.claude/skills/examples/jira/add_comment.md), [list_transitions](.claude/skills/examples/jira/list_transitions.md), [transition_issue](.claude/skills/examples/jira/transition_issue.md), [move_to_board](.claude/skills/jira/move_to_board.md)
> Skill reference: [session-init](.claude/skills/session-init.skill.md)
> Skill reference: [review-architecture](.claude/skills/review-architecture.md)
> Skill reference: [domain-context](.claude/skills/domain-context.skill.md)
> CML skills: [cml](.claude/skills/cml/)
> Skill reference: [design-gate](.claude/skills/design/design-gate.skill.md)

# Groom Jira Epic: $ARGUMENTS.epic

## Prerequisites

**This command requires an Epic with an associated PRP** (created by `/plan` command).

**Recommended:** Run `/validate-plan $ARGUMENTS.epic` before grooming to ensure PRP completeness.

**Auto-Transition:** If the Epic is not in GROOMING status, this command will automatically transition it to GROOMING before proceeding.

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/18] Grooming...`).

1. Phase 0: Initialize session and set step label
2. Phase 0.5: Design Session Inheritance
3. Phase 1: Fetch Epic, validate type, ensure GROOMING status
4. Phase 2: Find and parse PRP for implementation tasks
5. Phase 2.5: Domain-driven issue derivation from CML design + per-issue deviation check
6. Phase 3: Calculate task dependencies and execution order
7. Phase 4: Create Jira issues under Epic (including explicit test task issues)
8. Phase 4.5: Set tier-based priority and labels on all issues
9. Phase 5: Add dependency links to all issues
10. Phase 6: First Issue Review — completeness and accuracy
11. Phase 7: Architectural Review — project alignment
12. Phase 8: Second Issue Review — final validation
13. Phase 9: Transition all issues to To Do and register with Kanban board
14. Phase 10: Update Epic with dependency graph comment
15. Phase 10.5: Evaluate grooming completeness
16. Phase 11: Transition Epic to To Do and set outcome label
17. Phase 11.5: Consolidation Check (creation-time hint)
18. Phase 12: Report performance metrics

**START NOW: Begin Phase 0/Step 0.**

---

## Phase 0: Initialize Session

**[phase 0/18] Initializing session...**

1. Retrieve prior grooming patterns from AgentDB:
   ```bash
   npx tsx .claude/skills/agentdb/reflexion_retrieve_relevant.ts \
     '{"task": "$ARGUMENTS.epic groom PRP issue creation", "k": 3}'
   ```

2. Set step label on the Epic (preserve existing labels):
   ```bash
   CURRENT_LABELS=$(npx tsx .claude/skills/issues/get_issue.ts \
     '{"issue_key": "$ARGUMENTS.epic", "fields": ["labels"]}' | \
     python3 -c "import sys,json; d=json.load(sys.stdin); labels=d[\"fields\"][\"labels\"]; \
   labels=[l for l in labels if not l.startswith(\"step:\")]; labels.append(\"step:grooming\"); \
   print(json.dumps(labels))")
   npx tsx .claude/skills/issues/update_issue.ts \
     "{\"issue_key\": \"$ARGUMENTS.epic\", \"labels\": $CURRENT_LABELS}"
   ```

---

## Phase 0.5: Design Session Inheritance

**[phase 0.5/18] Checking design session linkage...**

> Skill reference: [design-gate](.claude/skills/design/design-gate.skill.md)

### Step 1: Check PRP for design linkage

Retrieve the PRP for this Epic (from AgentDB or the Jira Epic description). Scan for a
`## Design Artifacts` section. If present, extract the `session_id` value.

```bash
npx tsx .claude/skills/agentdb/recall_query.ts \
  '{"key": "planned-$ARGUMENTS.epic", "namespace": "${TENANT_NAMESPACE}"}'
```

### Step 2: Session found in PRP

Load `${DESIGN_DOCS_PATH}/sessions/{session_id}/state.json` and store session_id as
`LINKED_DESIGN_SESSION`.

Print:
```
[design] Linked session: {session_id}
  Status: {overall_status}
  Phases complete: {list of complete phases}
```

### Step 3: No session in PRP — fallback discovery

If no `## Design Artifacts` section found in PRP:

1. Classify work type from Epic title + description using the classification table in
   `design-gate.skill.md`. Store as `WORK_TYPE`.

2. Follow `design-gate:discover` with Epic title + description as `context` and `WORK_TYPE`.

3. Apply same handling as `/plan` Phase 0.5 Step 3:
   - Sessions found: auto-select top match (score > 0.5), store as `LINKED_DESIGN_SESSION`
   - `non-functional`: skip silently, set `LINKED_DESIGN_SESSION` to `none`
   - `platform-infra`, no sessions: emit `[DESIGN NOTE]`, set `LINKED_DESIGN_SESSION` to `none`
   - `ui-feature`/`api-feature`/`backend-infra`, no sessions: emit `[DESIGN WARNING]` with
     applicable phases listed, set `LINKED_DESIGN_SESSION` to `none`

---

## Phase 1: Fetch Epic, Validate Type, Ensure GROOMING Status

**[phase 1/18] Loading Epic...**

1. Fetch the Epic:
   ```bash
   npx tsx .claude/skills/issues/get_issue.ts \
     '{"issue_key": "$ARGUMENTS.epic", "fields": "key,summary,description,issuetype,status,labels,comment", "expand": "renderedFields"}'
   ```

2. Validate `issuetype.name === "Epic"`. If not — STOP. Report: "$ARGUMENTS.epic is not an Epic."

3. If status is not `GROOMING`: find and apply the GROOMING transition:
   ```bash
   npx tsx .claude/skills/issues/list_transitions.ts '{"issue_key": "$ARGUMENTS.epic"}'
   npx tsx .claude/skills/issues/transition_issue.ts '{"issue_key": "$ARGUMENTS.epic", "transition_name": "Grooming"}'
   ```

4. Store Epic summary as `EPIC_SUMMARY`.

---

## Phase 2: Find and Parse PRP

**[phase 2/18] Locating PRP document...**

1. Search Epic comments for a "PRP Created" comment with a file path. Also check AgentDB:
   ```bash
   npx tsx .claude/skills/agentdb/recall_query.ts \
     '{"key": "planned-$ARGUMENTS.epic", "namespace": "${TENANT_NAMESPACE}"}'
   ```

2. Read the PRP file:
   ```bash
   cat ${PROJECT_ROOT}/${DOCS_REPO}/PRPs/[path]/PRP-XXX-{slug}.md
   # or search:
   grep -rl "$ARGUMENTS.epic" ${PROJECT_ROOT}/${DOCS_REPO}/PRPs/ | head -3
   ```

3. If no PRP found → STOP. Report: "No PRP found for $ARGUMENTS.epic. Run `/plan` first."

4. Parse and extract from the PRP:
   - `PRP_AFFECTED_REPOS` ← `**Affects**:` field
   - `PRP_DESIGN_SESSION` ← `**Design Session**:` field
   - All `### Implementation Tasks` sections, organized by repository
   - All `### Test Infrastructure Impact` sub-sections — **read every sub-section including
     e2e-tests, lambda-functions (unit/hurl/integration), and frontend-app (Pact) explicitly**
   - Acceptance criteria per repository
   - The dependency graph from `**Dependencies**:` and task ordering notes

Store the full list as `PRP_TASKS[]`. Each entry captures:
- Title
- Description / acceptance criteria
- Repository
- Explicit test files and run commands (from Test Infrastructure section)
- Dependencies (other task titles)
- Whether it is a test task (from Test Infrastructure section)
- Task type (derive from title, description, AND acceptance criteria signals):
  - `operational` if title/description contains: `run `, `execute `, `make `, `AWS profile`, `no code changes`, `requires prod profile`, `manual step`, `operator`; OR acceptance criteria contain: `completes without error`, `exits 0`, `command succeeds`
  - `research` if title/description contains: `discovery`, `audit`, `confirm`, `verify`, `document`, `schema discovery`, `investigate`, `spike`, `discovery only`, `document the`, `confirm field names`, `update PRP`, `update Open Questions`; OR acceptance criteria contain: `documented`, `confirmed`, `finding documented`, `no PR needed`
  - `implementation` (default) for all others
---

## Phase 2.5: Domain-Driven Issue Derivation and Per-Issue Deviation Check

**[phase 2.5/18] Domain model alignment and deviation checks...**

### CML Cross-Reference

If `${TENANT_DOMAIN_PATH}` is unset or `domain-index.json` does not exist at
`${TENANT_DOMAIN_PATH}/${TENANT_DOMAIN_INDEX:-domain-index.json}`, skip the CML
cross-reference and log: `[domain] CML cross-reference skipped — domain model not configured.`

Otherwise, load `domain-index.json` to validate that all
repository-level tasks align with bounded context boundaries. Flag any task that crosses
a context boundary without an explicit integration event as a **WARNING**.

### Per-Issue Deviation Check

For EACH drafted issue (title + description + acceptance criteria):

If `LINKED_DESIGN_SESSION` is set and not `none`:

Follow `design-gate:check-deviation` — pass the full issue draft text as `content` and
`LINKED_DESIGN_SESSION` as `session_ids`.

**If `[DESIGN DEVIATION]` warnings are found:**

Append inline to the issue description draft BEFORE calling `create_issue`:

```markdown
---
> **Design Review Note**
> ⚠️ {finding description}
> Suggested resolution: {resolution}
> Reference: session `{session_id}` — {state.json field path}
```

Cap at 3 annotations per issue. Multiple findings each get their own block.

The architectural reviewer in Phase 7 will assess each annotation. Never delay or block
issue creation. Create the issue with the annotations included.

---

## Phase 3: Calculate Task Dependencies and Execution Order

**[phase 3/18] Calculating dependency tiers...**

1. Build a dependency graph from `PRP_TASKS[]` using explicit dependency annotations in the PRP.
2. Use topological sort to assign a **tier number** to each task:
   - Tier 1: no dependencies (start immediately)
   - Tier 2: depends only on Tier 1 tasks
   - Tier N: depends on tasks in Tier N-1 or lower
3. Test tasks (from Phase 4.2) sit in the final tiers — after all implementation tasks they verify.
4. Print the tier breakdown:
   ```
   Tier 1 (Highest): {task titles}
   Tier 2 (High):    {task titles}
   Tier 3 (Medium):  {task titles}
   ...
   ```

---


## Phase 3.5: Skeleton-First Issue Sequencing

**[phase 3.5/18] Ensuring skeleton issues exist...**

### Step 1: Check for Existing Skeleton Issues

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "parent = $ARGUMENTS.epic AND labels = skeleton", "fields": ["key", "summary", "status", "labels"]}'
```

### Step 2: Create Skeleton if Missing

If NO skeleton issues exist for this epic:

```
Invoke /create-skeleton $ARGUMENTS.epic
Invoke /review-skeleton $ARGUMENTS.epic
If NEEDS_FIXES: invoke /fix-skeleton, re-review (max 2 cycles)
If REJECTED after 2 cycles: escalate to user
If APPROVED: proceed
```

### Step 3: Skeleton-Aware Dependency Planning

When creating non-skeleton issues in Phase 4:
- Every non-skeleton implementation issue MUST include `is_blocked_by` links to the
  relevant skeleton issue(s) for its repository
- Skeleton issues are assigned to Tier 1 (highest priority, no blockers)
- Non-skeleton issues begin at Tier 2 or higher

### Step 4: Skeleton Acceptance Criteria

Every skeleton issue MUST include E2E test creation as part of its acceptance criteria:
- Skeleton issues for frontend repos: must include stub page + route
- Skeleton issues for backend repos: must include stub handler + API route
- Skeleton E2E issue: must include journey test for the skeleton path

---
## Phase 4: Create Jira Issues Under Epic

**[phase 4/18] Creating Jira issues...**

For each task in `PRP_TASKS[]` that is NOT a test task:

Determine issue type and workflow header based on task type:
- `operational` or `research` tasks → `{"name": "Task"}` with workflow header
- `implementation` tasks → `{"name": "Story"}` (default)

```bash
# Set conditional issue type
ISSUE_TYPE=$([ "$TASK_TYPE" = "operational" ] || [ "$TASK_TYPE" = "research" ] && echo "Task" || echo "Story")

# Set workflow header for non-implementation tasks
WORKFLOW_HEADER=""
if [ "$TASK_TYPE" = "operational" ]; then
  WORKFLOW_HEADER="**Workflow:** Direct execution - no PR required. Complete by running the specified commands and marking Done.\n\n"
elif [ "$TASK_TYPE" = "research" ]; then
  WORKFLOW_HEADER="**Workflow:** Discovery only - no PR required. Complete by documenting findings in a comment and marking Done.\n\n"
fi

npx tsx .claude/skills/issues/create_issue.ts "{
  "project_key": "${TENANT_PROJECT}",
  "summary": "{task title}",
  "description": "${WORKFLOW_HEADER}{task description with acceptance criteria}",
  "issuetype": {"name": "$ISSUE_TYPE"},
  "parent": {"key": "$ARGUMENTS.epic"},
  "labels": ["repo-{repository-name}"]
}"
```

Store each created issue key in `CREATED_ISSUES[]` with its task title and tier.

### 4.2 Explicit Test Task Issues

**These are the most frequently missed tasks in grooming. Every non-empty test section in
the PRP MUST produce a dedicated Jira issue.**

#### e2e-tests Test Issues

**If the PRP `### e2e-tests Tests` section names journey files, page objects, or test-ids:**

```bash
npx tsx .claude/skills/issues/create_issue.ts '{
  "project_key": "${TENANT_PROJECT}",
  "summary": "e2e-tests: {Epic summary} — Playwright journey tests",
  "description": "Write/update Playwright E2E journey tests.\n\n**Journey spec:** tests/journeys/{domain}.spec.ts\n**Page objects:** pages/{PageName}.ts\n**test-ids.ts:** {new test-id constants or none}\n\n**Run:** npx playwright test tests/journeys/{domain}.spec.ts --project=chromium\n\n**Acceptance Criteria:**\n{e2e-tests acceptance criteria from PRP}",
  "issuetype": {"name": "Story"},
  "parent": {"key": "$ARGUMENTS.epic"},
  "labels": ["repo-e2e-tests", "test-task"]
}'
```

#### lambda-functions Hurl Smoke Test Issue

**If the PRP `### lambda-functions Tests` section names specific hurl files:**

```bash
npx tsx .claude/skills/issues/create_issue.ts '{
  "project_key": "${TENANT_PROJECT}",
  "summary": "lambda-functions: {feature} — hurl smoke tests",
  "description": "Add/update hurl smoke test files.\n\n**Files:** {hurl file names from PRP}\n**Run:** hurl --test tests/hurl/{file}.hurl\n\n**Acceptance Criteria:**\n{hurl criteria from PRP}",
  "issuetype": {"name": "Story"},
  "parent": {"key": "$ARGUMENTS.epic"},
  "labels": ["repo-lambda-functions", "test-task"]
}'
```

#### lambda-functions Integration Test Issue

**If the PRP `### lambda-functions Tests` section names integration test changes:**

```bash
npx tsx .claude/skills/issues/create_issue.ts '{
  "project_key": "${TENANT_PROJECT}",
  "summary": "lambda-functions: {feature} — integration tests",
  "description": "Add/update integration tests.\n\n**File:** tests/integration/integration_test.go\n**Run:** go test ./tests/integration/...\n\n**Acceptance Criteria:**\n{integration test criteria from PRP}",
  "issuetype": {"name": "Story"},
  "parent": {"key": "$ARGUMENTS.epic"},
  "labels": ["repo-lambda-functions", "test-task"]
}'
```

#### frontend-app Pact Consumer Contract Issue

**If the PRP `### frontend-app Tests` section names Pact contract files:**

```bash
npx tsx .claude/skills/issues/create_issue.ts '{
  "project_key": "${TENANT_PROJECT}",
  "summary": "frontend-app: {feature} — Pact consumer contract tests",
  "description": "Add/update Pact consumer contract tests.\n\n**Contract files:** pact/consumers/{feature}.pact.spec.ts\n**Run:** npm run test:pact\n\n> NOTE: npm run test:pact is MANDATORY and must pass before PR merge.\n\n**Acceptance Criteria:**\n{Pact criteria from PRP}",
  "issuetype": {"name": "Story"},
  "parent": {"key": "$ARGUMENTS.epic"},
  "labels": ["repo-frontend-app", "test-task"]
}'
```

#### Other Repository Test Issues

For any other affected repository whose PRP Test Infrastructure section has non-trivial
content (not just "none"), create a dedicated test task issue following the same pattern.
Reference the exact files and run commands from the PRP.

---

## Phase 4.5: Set Tier-Based Priority and Labels

**[phase 4.5/18] Setting tier-based priorities...**

After creating all issues, set the Jira priority and `tier-N` label on each issue based on its dependency tier.

### Tier-to-Priority Mapping

| Tier | Jira Priority | Rationale |
|------|---------------|-----------|
| 1 | Highest | No blockers — start immediately |
| 2 | High | Depends on Tier 1 only |
| 3 | Medium | Mid-execution dependencies |
| 4 | Low | Depends on infra + scaffolds |
| 5 | Low | Post-integration validation |
| 6+ | Lowest | Final deployment gate |

**Tiers 4 and 5 both map to Low** (Jira has only 5 priority levels). **Tiers beyond 6: Lowest.**

For each issue:

```bash
npx tsx .claude/skills/issues/update_issue.ts '{
  "issue_key": "{ISSUE_KEY}",
  "priority": "{PRIORITY_FROM_TABLE}",
  "labels": ["{existing_labels...}", "tier-{N}"]
}'
```

**Label format:** `tier-1`, `tier-2`, etc. (dash separator).

**Preserve existing labels** (`epic-*`, `repo-*`, `test-task`, domain labels) — always include them in the labels array.

---

## Phase 5: Add Dependency Links to All Issues

**[phase 5/18] Adding dependency links...**

For each issue that has dependencies on other created issues:

```bash
npx tsx ~/.claude/skills/jira/add_issue_link.ts '{
  "inward_issue_key": "{ISSUE_KEY}",
  "outward_issue_key": "{BLOCKING_ISSUE_KEY}",
  "link_type": "Blocks"
}'
```

Print a summary of all links created.

---

## Phase 6: First Issue Review — Completeness and Accuracy

**[phase 6/18] First review pass...**

Review all created issues as if picking up this work with zero context:

- [ ] Every PRP implementation task has a corresponding Jira issue
- [ ] Every non-empty PRP test section has a corresponding test task issue
- [ ] e2e-tests: issue exists if PRP `### e2e-tests Tests` section is non-empty
- [ ] lambda-functions hurl: issue exists if PRP names specific hurl files
- [ ] lambda-functions integration: issue exists if PRP names integration test changes
- [ ] frontend-app Pact: issue exists if PRP names Pact contract files
- [ ] Each issue description contains enough context to implement without reading the PRP
- [ ] Acceptance criteria in each issue map to PRP requirements
- [ ] Repository labels are correct (`repo-{name}`)
- [ ] No placeholders or TODOs remain in issue descriptions

Flag gaps as **BLOCKING** (missing issue) or **WARNING** (incomplete description).

---

## Phase 7: Architectural Review — Project Alignment

**[phase 7/18] Architectural review...**

- Does the issue set fully cover the PRP proposed solution without gaps?
- Are any issues scoped too large for a single `/work` invocation? (If so, split them)
- Do dependency links reflect the actual execution order?
- Are bounded context boundaries respected across repository issues?
- Do design deviation annotations (Phase 2.5) need resolution before implementation?
- Are cross-repository type synchronization tasks present when the PRP calls for them?

Reference `${PROJECT_ROOT}/${DOCS_REPO}/reference/patterns/` for project patterns.

---

## Phase 8: Second Issue Review — Final Validation

**[phase 8/18] Final review pass...**

Confirm with all prior findings in mind:

- All BLOCKING gaps from Phases 6–7 are resolved or documented
- Every created issue is coherent end-to-end
- Test task issues (e2e-tests, lambda-functions hurl/integration, frontend-app Pact) are present where required
- Tier assignments and priority values are consistent

---

## Phase 9: Transition All Issues to To Do and Register with Kanban Board

**[phase 9/18] Transitioning issues to To Do and registering with board...**

For each issue in `CREATED_ISSUES[]`:

```bash
npx tsx .claude/skills/issues/list_transitions.ts '{"issue_key": "{ISSUE_KEY}"}'
npx tsx .claude/skills/issues/transition_issue.ts '{"issue_key": "{ISSUE_KEY}", "transition_name": "To Do"}'
```

**After ALL issues are transitioned**, register them with the Kanban board so they appear in board columns (not just the backlog). API-created issues lack a board rank and won't render on the board without this step.

```bash
npx tsx ~/.claude/skills/jira/move_to_board.ts '{"board_id": 35, "issue_keys": ["{ALL_CREATED_ISSUE_KEYS}"]}'
```

> **Board ID reference:** project board (configure via JIRA_BOARD_ID). Use `list_boards.ts` for other projects.

Print a count: `Transitioned {N} issues to To Do and registered with board.`

---

## Phase 10: Update Epic with Dependency Graph Comment

**[phase 10/18] Updating Epic comment...**

```bash
npx tsx .claude/skills/issues/add_comment.ts '{
  "issue_key": "$ARGUMENTS.epic",
  "body": "**Grooming Complete**\n\n**Issues Created:** {N} ({M} test task issues)\n\n**Dependency Tiers:**\n| Tier | Priority | Issues |\n|---|---|---|\n{tier rows}\n\n**Linked Design Session:** {LINKED_DESIGN_SESSION or None}\n\n**Issue Index:**\n| Tier | Key | Summary | Repo |\n|---|---|---|---|\n{issue rows}"
}'
```

---

## Phase 10.5: Evaluate Grooming Completeness

**[phase 10.5/18] Evaluating completeness...**

| Check | Status |
|---|---|
| All PRP implementation tasks have issues | PASS/FAIL |
| e2e-tests test task issue created | PASS/SKIP (not in PRP) |
| lambda-functions hurl test task issue created | PASS/SKIP (not in PRP) |
| lambda-functions integration test task issue created | PASS/SKIP (not in PRP) |
| frontend-app Pact test task issue created | PASS/SKIP (not in PRP) |
| Operational/research tasks correctly typed as Task (not Story) | PASS/FAIL |
| Tier labels set on all issues | PASS/FAIL |
| Dependency links added | PASS/FAIL |
| Design deviations annotated where applicable | PASS/SKIP |
| All issues transitioned to To Do | PASS/FAIL |

Any FAIL → do NOT transition the Epic. Document the failure and stop.

---

## Phase 11: Transition Epic to To Do and Set Outcome Label

**[phase 11/18] Finalizing Epic...**

1. Transition Epic to `To Do`:
   ```bash
   npx tsx .claude/skills/issues/list_transitions.ts '{"issue_key": "$ARGUMENTS.epic"}'
   npx tsx .claude/skills/issues/transition_issue.ts '{"issue_key": "$ARGUMENTS.epic", "transition_name": "To Do"}'
   ```

2. Set outcome label (preserve existing labels):
   - On success: add `outcome:success-grooming-complete`
   - On failure: add `outcome:failure-grooming-incomplete` and do NOT transition

---

## Phase 11.5: Consolidation Check (Creation-Time Hint)

**[phase 11.5/18] Checking for consolidation opportunities...**

After all issues are created and the Epic is transitioned, check the garden cache for open
issues that overlap in scope with any of the groomed issues:

```bash
CACHE_DIR="${HOME}/.cache/garden"
if [[ -f "${CACHE_DIR}/issues/index.json" ]]; then
  cache_age_check=$(python3 -c "
import json, os, time
meta_path = os.path.expanduser('~/.cache/garden/cache-meta.json')
if not os.path.exists(meta_path): print('stale'); exit()
meta = json.load(open(meta_path))
created = meta.get('createdAt', '')
if not created: print('stale'); exit()
import datetime
age = time.time() - datetime.datetime.fromisoformat(created.replace('Z','+00:00')).timestamp()
print('fresh' if age < 14400 else 'stale')  # 4h TTL
")
  if [[ "$cache_age_check" == "fresh" ]]; then
    echo "Checking for consolidation opportunities..."
    # Search index.json for open issues in the same repository or module
    # referenced in the newly groomed issues' descriptions
  fi
fi
```

If candidates found in the same repository or module path:
1. Present suggestion: "PROJ-XXX and NEW-KEY both touch `{module/path}` — consider working them in a single PR"
2. Ask user:
   - **Confirm** → add `consolidate-with:PROJ-XXX` label to both issues + add a cross-link comment on each
   - **Decline** → store the declination in AgentDB:
     ```bash
     npx tsx ~/.claude/skills/agentdb/pattern_store.ts '{
       "task_type": "consolidation-decline:PROJ-XXX:NEW-KEY",
       "approach": "declined",
       "success_rate": 0
     }'
     ```
3. If no cache present or no candidates found: skip silently

---

## Phase 12: Report Performance Metrics

**[phase 12/18] Storing metrics...**

```bash
npx tsx .claude/skills/agentdb/reflexion_store_episode.ts '{
  "session_id": "${TENANT_NAMESPACE}",
  "task": "groom $ARGUMENTS.epic",
  "reward": {0.0-1.0 based on completeness score},
  "success": {true/false},
  "metadata": {
    "issues_created": {N},
    "test_task_issues": {M},
    "design_session": "{LINKED_DESIGN_SESSION}",
    "tier_count": {max tier}
  }
}'
```

Print final summary:
```
Grooming complete for $ARGUMENTS.epic
  Issues created: {N} ({M} test task issues)
  Tiers: {max_tier}
  Design session: {LINKED_DESIGN_SESSION or None}
  Next step: Run /validate-groom $ARGUMENTS.epic
```

---

## Anti-Patterns

| Don't | Do Instead |
|---|---|
| Skip Phase 2 PRP test section parsing | Parse every Test Infrastructure sub-section explicitly |
| Omit test task issues | Create dedicated issues for each non-empty test section |
| Merge all tests into one "write tests" issue | Separate e2e-tests, lambda-functions hurl, lambda-functions integration, frontend-app Pact |
| Skip Phase 4.5 tier labels | Every issue must have `tier-N` label and correct priority |
| Create issues without acceptance criteria | Each issue must be self-contained |
| Scope issues too large | Each issue should be completable in a single `/work` invocation |
| Skip design deviation check | Phase 2.5 must run even when LINKED_DESIGN_SESSION seems obvious |

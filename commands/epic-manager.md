<!-- MODEL_TIER: opus -->
<!-- DISPATCH: Spawn a Task subagent with model: "opus" to execute this command. -->

---
description: Drive a single Jira epic to Done through architect review, implementation, QA validation, reflection, and close
arguments:
  - name: epic
    description: Jira Epic key (e.g., PROJ-2581)
    required: true
---

# Epic Manager: $ARGUMENTS.epic

## MANDATORY: Create Phase TodoWrite Items

Before doing anything else, create these tracking items:

```
TodoWrite({
  todos: [
    { content: "Phase 0: Load and reconcile state vs Jira", status: "pending" },
    { content: "Phase 1: Architect review — gap analysis", status: "pending" },
    { content: "Phase 1.5: Code integration audit for suspect Done issues", status: "pending" },
    { content: "Phase 2: Group issues by repository", status: "pending" },
    { content: "Phase 3: Implement — Coder Tasks per repo group (work→review→fix-pr→resolve-pr)", status: "pending" },
    { content: "Phase 4: Validate all issues (validate each; re-work any failures)", status: "pending" },
    { content: "Phase 4.5: Epic reflection — collect and synthesize", status: "pending" },
    { content: "Phase 5: Close epic", status: "pending" }
  ]
})
```

---

## Overview

Drives a single epic from architect review through implementation, QA, and reflection to close.
Groups child issues by target repository. Issues within the same repo are serial (one PR at a time).
Issues across repos run in parallel via separate Coder Tasks.

**Workflow per issue (MANDATORY — no shortcuts):**
`/work` → `/review` → `/fix-pr` (if review or CI finds issues) → `/resolve-pr` → (then validate at Phase 4)

**Done means:** all issues are complete, deployed to dev, and have passed `/validate`. No unintended effects on other features, pipelines, or environments.

State: `$TENANT_DOCS_PATH/operations/agent-state/{cycleKey}/{user-email}/epic-manager-$ARGUMENTS.epic.json`
**Jira is always authoritative** — state files are resume hints only.

---

## Subagent Monitoring Policy (APPLY THROUGHOUT)

All Coder Tasks spawned in Phase 3 are subject to these rules. Apply them continuously during Phase 3.

### Detecting a Stuck or Dead Subagent

A Coder Task is considered **stuck** if:
- It has not reported progress within a reasonable observation window
- It returns an error indicating context exhaustion or premature termination
- It exits without returning the expected `{"repo": "...", "status": "..."}` JSON result

### Restart Protocol

When a stuck or dead Coder Task is detected:

1. **Determine the current step** for the issue it was working:
   ```bash
   npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "{issueKey}", "fields": ["status", "labels"]}'
   ```
2. **Identify the resume point** from the Jira step label:
   - `step:planning` → restart with `/work {issueKey}` (full restart)
   - `step:implementing` → restart with `/work {issueKey}` (will detect in-progress plan)
   - `step:awaiting-ci` → restart Coder Task instructing it to run `/review` then proceed
   - `step:ready-for-review` → restart Coder Task instructing it to run `/review`
   - `step:reviewing` → restart Coder Task instructing it to run `/fix-pr` then `/resolve-pr`
   - `step:fixing-pr` → restart Coder Task instructing it to run `/fix-pr` then `/resolve-pr`
   - `step:merging` → check if PR was merged; if yes, mark complete; if no, run `/resolve-pr`
   - No step label / In Progress → restart with `/work {issueKey}`

3. **Spawn a new Coder Task** with the same prompt but adjusted starting point (see Phase 3.1 for the full prompt template). Pass `resumeFrom` context explicitly.

4. **Update state** to record the restart and the new subagent reference.

### Context Exhaustion Handling

If a Coder Task reports running out of context mid-`/work`:
- The issue will be in an intermediate state tracked by its Jira step label
- **Do not** attempt to continue in the same subagent
- Use the restart protocol above to spawn a fresh subagent
- The new subagent uses `/work {issueKey}` which will detect the existing worktree and plan via Jira step labels and resume correctly

---

## Phase 0: Load & Reconcile

Mark Phase 0 TodoWrite item as in_progress.

### 0.1 Retrieve patterns from AgentDB

```bash
npx tsx ~/.claude/skills/agentdb/pattern_search.ts '{"task": "epic manager implementation architect qa reflection", "k": 5, "threshold": 0.5}'
npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts '{"task": "epic-manager $ARGUMENTS.epic", "k": 3, "threshold": 0.5}'
```

### 0.2 Resolve cycleKey and state paths

Look up the epic in roadmap.json:

```bash
python3 -c "
import json, os
r = json.load(open(os.path.expandvars('\$TENANT_DOCS_PATH') + '/initiatives/roadmap.json'))
e = next((x for x in r['epics'] if x['id'] == '$ARGUMENTS.epic'), None)
if e:
    print('CYCLE_KEY=' + e['cycleKey'])
    print('PRP_PATH=' + str(e.get('pRP', '')))
else:
    print('NOT_FOUND')
"
```

**GUARD: If output is `NOT_FOUND`:**
Print: `ERROR: Epic $ARGUMENTS.epic is not in roadmap.json. Add it to roadmap.json before running /epic-manager.`
**Stop. Do not proceed.**

Set variables:
```bash
GIT_USER_EMAIL=$(git config user.email)
CYCLE_KEY=<value from above>
PRP_PATH=<value from above>
STATE_DIR="$TENANT_DOCS_PATH/operations/agent-state/${CYCLE_KEY}/${GIT_USER_EMAIL}"
STATE_FILE="${STATE_DIR}/epic-manager-$ARGUMENTS.epic.json"
mkdir -p "$STATE_DIR"
```

Create cycle `_index.yaml` if it does not exist:

```bash
CYCLE_INDEX="$TENANT_DOCS_PATH/operations/agent-state/${CYCLE_KEY}/_index.yaml"
if [ ! -f "$CYCLE_INDEX" ]; then
cat > "$CYCLE_INDEX" << EOF
directory: ${CYCLE_KEY}
description: "Agent state for ${CYCLE_KEY} — one subdirectory per developer email"
contents: []
EOF
fi
```

### 0.3 Load own state file

If `$STATE_FILE` exists:
- Print: `Resuming epic-manager $ARGUMENTS.epic (phase: {state.phase})`
- Parse JSON. Note `phase`, `repoGroups`, `architectReviewDone`, `validateAllDone`, `validationResults`.

If `$STATE_FILE` does not exist:
- Print: `Starting fresh: epic-manager $ARGUMENTS.epic`
- Initialize state:
```json
{
  "epic": "$ARGUMENTS.epic",
  "cycleKey": "<CYCLE_KEY>",
  "startedAt": "<ISO timestamp>",
  "phase": "load",
  "repoGroups": {},
  "gapsIdentified": [],
  "gapIssuesCreated": [],
  "crossEpicIssues": [],
  "architectReviewDone": false,
  "validateAllDone": false,
  "validationResults": {},
  "coderTaskRestarts": {},
  "prpAvailable": false
}
```

### 0.4 Read peer state files

```bash
ls "$TENANT_DOCS_PATH/operations/agent-state/${CYCLE_KEY}/" 2>/dev/null
```

For each peer directory (email ≠ current user), read their `epic-manager-$ARGUMENTS.epic.json` if it exists. Note any issues they list as completed — reconcile against Jira below.

### 0.5 Skeleton Verification

Before proceeding with implementation, verify the epic has a walking skeleton defined and validated.

1. Search for skeleton issues:
```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "parent = $ARGUMENTS.epic AND labels = skeleton", "fields": ["key", "summary", "status", "labels"]}'
```

2. **If NO skeleton issues found:**
   - Invoke `/create-skeleton $ARGUMENTS.epic`
   - Invoke `/review-skeleton $ARGUMENTS.epic`
   - If review verdict is NEEDS_FIXES: invoke `/fix-skeleton $ARGUMENTS.epic`, then re-review (max 2 cycles)
   - If review verdict is REJECTED after 2 fix cycles: escalate to user, do not proceed with implementation
   - Re-fetch skeleton issues after creation

3. **If skeleton issues exist but NOT all have `outcome:success-validation` label:**
   - Identify unvalidated skeleton issues
   - Add skeleton issues to the FRONT of the work queue in every affected repo group
   - Skeleton issues MUST be completed and validated before ANY non-skeleton issue begins work
   - Log: `Skeleton issues queued first: {skeleton_issue_keys}`

4. **If all skeleton issues have `outcome:success-validation`:**
   - Log: `Skeleton validated - proceeding with full implementation`

Store skeleton status in state: `skeletonVerified: true|false`, `skeletonIssues: [...]`

### 0.6 Fetch epic and child issues from Jira

```bash
npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.epic", "fields": ["summary", "status", "description", "labels", "components"]}'
```

Fetch child issues:

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${PROJECT_KEY} AND (\"Epic Link\" = $ARGUMENTS.epic OR parent = $ARGUMENTS.epic)", "fields": ["key", "summary", "status", "labels", "components", "priority"], "max_results": 100}'
```

**Skeptical Done-Issue Audit:** for each issue where Jira status = Done:

1. **Check validation evidence:** Look for `outcome:validated` or `pr:{repo}/{N}` labels
2. **If validation evidence exists:** mark as completed in repoGroups state (these will be skipped in Phase 3)
3. **If lacking validation evidence:** add to `suspectDoneIssues` list in state
4. **Log WARNING:** for each suspect issue: `WARNING: {issueKey} marked Done but lacks outcome:validated or PR evidence - queuing for Phase 1.5 audit`

Store `suspectDoneIssues` in state for Phase 1.5 processing.

### 0.7 Check for cross-epic impact comments

```bash
npx tsx ~/.claude/skills/issues/list_comments.ts '{"issue_key": "$ARGUMENTS.epic"}'
```

For each comment containing "Cross-epic impact" or "⚠️ Conflict" that has not yet been acknowledged with an "ACK:" reply:
- Understand the required action
- Reply with acknowledgment:

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.epic", "body": "ACK: Impact noted — {description of what was changed}. Planned action: {action}. Will address in Phase {N}."}'
```

### 0.8 Read PRP

If `PRP_PATH` is non-empty:
```bash
test -f "$TENANT_DOCS_PATH/$PRP_PATH" && cat "$TENANT_DOCS_PATH/$PRP_PATH" || echo "PRP_FILE_MISSING"
```

**GUARD: If PRP file is missing or PRP_PATH is empty:**
Print: `WARNING: No PRP available for $ARGUMENTS.epic. Architect review will be limited to issue-level analysis only.`
Set `prpAvailable: false` in state. Continue.

If PRP is found: set `prpAvailable: true` in state.

### 0.9 Commit state

```bash
cd $TENANT_DOCS_PATH && git pull --rebase && git add operations/agent-state/ && git commit -m "chore: epic-manager $ARGUMENTS.epic phase-0 checkpoint [$(git config user.email)]" && git push
```

Mark Phase 0 TodoWrite item as completed.

---

## Phase 1: Architect Review

Mark Phase 1 TodoWrite item as in_progress.

### **GUARD: Skip if `architectReviewDone: true` in state**

If state.architectReviewDone is true:
Print: `Skipping Phase 1 — architect review already done`
Mark Phase 1 TodoWrite item as completed and proceed directly to Phase 2.

### 1.1 Spawn Architect Task

Spawn a Task subagent with model: opus. Provide this prompt:

> You are a senior architect reviewing an epic before implementation begins.
>
> Epic: $ARGUMENTS.epic
> PRP available: {state.prpAvailable}
> PRP content (if available): {prp content or "No PRP — review issues only"}
>
> Child issues (key, summary, acceptance criteria):
> {issueList}
>
> Your job:
> 1. Identify gaps — functionality in the PRP (or implied by the epic description) not covered by any child issue
> 2. Flag ambiguous acceptance criteria that will cause implementation disputes
> 3. Identify cross-repo risks — shared types, API contracts, auth changes
> 4. Check dependency order — are issues sequenced correctly?
> 5. Identify potential unintended effects on other features, pipelines, or environments
>
> For each gap, create a Jira issue linked to epic $ARGUMENTS.epic:
> ```bash
> npx tsx ~/.claude/skills/issues/create_issue.ts '{"project_key": "${PROJECT_KEY}", "summary": "...", "issue_type": "Story", "description": "...", "labels": ["repo-XXX"], "parent": "$ARGUMENTS.epic"}'
> ```
>
> Before creating a gap issue, search for existing issues with the same title to avoid duplicates:
> ```bash
> npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${PROJECT_KEY} AND summary ~ \"...\" AND (\"Epic Link\" = $ARGUMENTS.epic OR parent = $ARGUMENTS.epic)", "fields": ["key", "summary"]}'
> ```
>
> Return JSON only:
> ```json
> {
>   "gaps": [{"description": "...", "createdIssueKey": "PROJ-XXX or null"}],
>   "ambiguousIssues": [{"key": "PROJ-XXX", "problem": "..."}],
>   "risks": [{"description": "...", "affectedRepos": [], "potentialSideEffects": "..."}],
>   "dependencyFixes": [{"issue": "PROJ-XXX", "mustComeAfter": "PROJ-YYY"}]
> }
> ```

### 1.2 Process architect output

- For each gap with a created issue key: add to `gapIssuesCreated` in state
- For each `ambiguousIssue`: post a comment on that Jira issue:
```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "PROJ-XXX", "body": "Architect review flagged ambiguous AC: {problem}. Please clarify before implementation."}'
```
- For each `dependencyFix`: update issue order in state

### 1.3 Mark complete and commit

Set `architectReviewDone: true`. Commit:

```bash
cd $TENANT_DOCS_PATH && git pull --rebase && git add operations/agent-state/ && git commit -m "chore: epic-manager $ARGUMENTS.epic phase-1 architect-review done [$(git config user.email)]" && git push
```

Mark Phase 1 TodoWrite item as completed.

---

## Phase 1.5: Code Integration Audit

Mark Phase 1.5 TodoWrite item as in_progress.

### **GUARD: Skip if no suspectDoneIssues in state**

If state.suspectDoneIssues is empty:
Print: `Skipping Phase 1.5 — no suspect Done issues found`
Mark Phase 1.5 TodoWrite item as completed and proceed to Phase 2.

### 1.5.1 Group suspect Done issues by repository

For each issue in `suspectDoneIssues`, group by target repository using the same logic as Phase 2.

### 1.5.2 Spawn Auditor Task per repo group

For each repo group containing suspect Done issues:

Spawn a Task subagent with model: sonnet. Provide this prompt:

> You are an Auditor agent verifying code integration for suspect Done issues in {repoName}.
>
> Epic: $ARGUMENTS.epic
> Issues to audit: {suspectIssueList — key and summary}
>
> These issues are marked Done in Jira but lack validation evidence. Your job:
> 1. **Verify genuine integration** — check if the work was actually completed and integrated
> 2. **Flag built-but-not-wired code** — components/features that exist but are not connected
>
> **Audit checklist by repository type:**
>
> **For frontend-app/sdk/dashboard:**
> - Search for component files, hooks, or utilities mentioned in issue summary
> - Check if components are imported in parent components or pages
> - Verify components are used in JSX/TSX rendering (not just imported)
> - Check Zustand store integration if state management was part of the issue
>
> **For lambda-functions/go-common:**
> - Check if Lambda functions are deployed and reachable via API Gateway
> - Verify API endpoints respond correctly (not 404 or unimplemented)
> - Check CloudWatch logs for function execution evidence
>
> **For migrations:**
> - Verify DynamoDB schema changes are applied (check table structure)
> - Confirm new fields/indexes exist and are accessible
>
> **Classification:**
> - **genuinelyIntegrated**: Work is complete and properly wired
> - **builtNotWired**: Code exists but not integrated (dead code)
> - **notImplemented**: No evidence of implementation found
>
> **For confirmed-integrated issues (genuinelyIntegrated):**
> - Add `outcome:validated` label to mark as trusted-complete
> - DO NOT re-work these in Phase 3
>
> **For built-but-not-wired or not-implemented issues:**
> - Transition back to To Do status
> - Add comment explaining what needs to be completed
> - Remove from `repoGroups.completedIssues` so they get re-worked in Phase 3
>
> Return JSON only:
> ```json
> {
>   "repo": "{repoName}",
>   "results": [
>     {"issue": "PROJ-XXX", "status": "genuinelyIntegrated", "evidence": "Component imported in Dashboard.tsx line 45"},
>     {"issue": "PROJ-YYY", "status": "builtNotWired", "reason": "Component exists but never imported"},
>     {"issue": "PROJ-ZZZ", "status": "notImplemented", "reason": "No matching files found"}
>   ]
> }
> ```

### 1.5.3 Process audit results and update state

For each audit result:
- `genuinelyIntegrated`: Add `outcome:validated` label, keep as completed in repoGroups
- `builtNotWired` or `notImplemented`: Transition to To Do, remove from completedIssues, add back to pending issues

Update state to remove processed issues from `suspectDoneIssues`.

### 1.5.4 Commit audit results

```bash
cd $TENANT_DOCS_PATH && git pull --rebase && git add operations/agent-state/ && git commit -m "chore: epic-manager $ARGUMENTS.epic phase-1.5 code-integration-audit done [$(git config user.email)]" && git push
```

Mark Phase 1.5 TodoWrite item as completed.
---

## Phase 2: Group Issues by Repository

Mark Phase 2 TodoWrite item as in_progress.

### **GUARD: Skip if `repoGroups` is already populated in state**

If state.repoGroups has at least one key:
Print: `Skipping Phase 2 — repo groups already built`
Mark Phase 2 TodoWrite item as completed and proceed to Phase 3.

### 2.1 Determine target repo for each issue

For each child issue (including any gap issues created in Phase 1), inspect its labels for a `repo-{name}` pattern:

```bash
npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "PROJ-XXX", "fields": ["labels", "components", "summary"]}'
```

**Repo assignment priority:**
1. First `repo-{name}` label found (alphabetical if multiple)
2. First component name that matches a known repo
3. Most-mentioned repo name in the issue description/summary
4. If no signal: assign to the repo most commonly used by other issues in this epic (fallback group `api-service`)

Log a warning for any issue without a repo label: `WARNING: PROJ-XXX has no repo label — assigned to {fallback} by heuristic.`

### 2.2 Build ordered repoGroups

```python
# Order issues within each group by priority (Highest→High→Medium→Low)
# Then apply dependencyFixes from architect review
repoGroups = {
  "frontend-app": {
    "issues": ["PROJ-2600", "PROJ-2601"],   # ordered
    "completedIssues": [],
    "currentIssue": "PROJ-2600",
    "status": "pending",
    "coderTaskRestarts": 0
  },
  "dashboard": {
    "issues": ["PROJ-2603"],
    "completedIssues": [],
    "currentIssue": "PROJ-2603",
    "status": "pending",
    "coderTaskRestarts": 0
  }
}
```

Save to state and commit:

```bash
cd $TENANT_DOCS_PATH && git pull --rebase && git add operations/agent-state/ && git commit -m "chore: epic-manager $ARGUMENTS.epic phase-2 repo-groups [$(git config user.email)]" && git push
```

Mark Phase 2 TodoWrite item as completed.

---

## Phase 3: Implement

Mark Phase 3 TodoWrite item as in_progress.

### **GUARD: If all repoGroups have `status: complete`, skip to Phase 4**

### 3.1 Spawn one Coder Task per pending repo group (parallel)

For each repo group with `status: pending`:

Spawn a Task subagent with model: sonnet. Provide this prompt (one per repo group):

> You are a Coder agent responsible for working issues in {repoName} for epic $ARGUMENTS.epic.
>
> Issues to complete in this order:
> {orderedIssues — one per line with key and summary}
>
> Already completed (skip these):
> {completedIssues}
>
> Current issue to start: {currentIssue}
> Resume from step: {resumeFrom — "beginning" or a specific step label like "step:ready-for-review"}
>
> **MANDATORY WORKFLOW — follow this sequence exactly for each issue:**
>
> **Step 1: /work**
> Run the /work command using the Skill tool:
> ```
> Skill(name="work", arguments="{issueKey}")
> ```
> The /work command handles: claiming the issue, creating a worktree, writing an implementation plan, TDD implementation, creating a PR, and transitioning to the appropriate step label. Do NOT skip /work. If resumeFrom indicates the issue is already past the planning/implementing phase, /work will detect the existing state and fast-forward appropriately.
>
> **Step 2: /review (MANDATORY — run immediately after PR exists, do NOT wait for CI)**
> After /work creates a PR, immediately run /review:
> ```
> Skill(name="review", arguments="{issueKey}")
> ```
> Do not wait for CI to finish before running /review. CI and review run in parallel.
>
> **Step 3: /fix-pr (run if review OR CI finds issues)**
> If /review returns `outcome:needs-changes` OR CI fails, run:
> ```
> Skill(name="fix-pr", arguments="{issueKey}")
> ```
> Repeat /fix-pr until both CI passes and review is approved.
>
> **Step 4: /resolve-pr (merge when CI green AND review approved)**
> Only when both CI passes and review is approved, run:
> ```
> Skill(name="resolve-pr", arguments="{issueKey}")
> ```
>
> **Step 5: Confirm merge and transition**
> After /resolve-pr, confirm the issue has transitioned to Validation status in Jira:
> ```bash
> npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "{issueKey}", "fields": ["status", "labels"]}'
> ```
> The issue must be in Validation status before marking it complete and moving to the next issue.
>
> **Step 6: Advance to next issue**
> Only after the current issue is confirmed in Validation (or Done) status, advance to the next issue in the list and repeat Steps 1-5.
>
> **Gap discovery during implementation:**
> If you discover a gap (missing functionality, blocking dependency, or regression risk) that is NOT covered by an existing issue:
> 1. Search for duplicates first:
>    ```bash
>    npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${PROJECT_KEY} AND summary ~ \"{gap description}\"", "fields": ["key", "summary", "status"]}'
>    ```
> 2. If no duplicate, create a new issue. Determine if it belongs to this epic ($ARGUMENTS.epic) or another:
>    - Belongs to this epic: create with `"parent": "$ARGUMENTS.epic"`
>    - Belongs to another epic: create without parent, then link to the correct epic
>    ```bash
>    npx tsx ~/.claude/skills/issues/create_issue.ts '{"project_key": "${PROJECT_KEY}", "summary": "...", "issue_type": "Story", "description": "...", "labels": ["repo-{repoName}"], "parent": "$ARGUMENTS.epic"}'
>    ```
> 3. Include the gap issue key in your completion report.
>
> **Unintended effect detection:**
> Before completing each issue, verify no unintended side effects by checking:
> - CI passes for the repository (no regressions in other tests)
> - No unexpected changes to shared types, API contracts, or auth flows
> - Pipelines for related repositories are not broken
>
> **E2E Gate Rules for Coder Tasks:**
> - Before writing any code: `/e2e-verify-red` must confirm the spec fails (enforced inside `/implement` Phase 0.9)
> - The ONLY exit from the implementation phase is `/e2e-verify-green` PASS on both viewports
> - If GREEN fails: fix the code and re-run — do NOT create a PR
> - If GREEN fails 3+ times: set `status: blocked`, `blocker: "e2e-green-gate"` in the task
>   result JSON and return — do not escalate by creating a partial PR
>
> **If you run out of context mid-/work:**
> Do not attempt to continue. Return immediately:
> `{"repo": "{repoName}", "status": "context_exhausted", "currentIssue": "{issueKey}", "currentStep": "check Jira step label"}`
>
> **If blocked at any step:**
> Stop and return:
> `{"repo": "{repoName}", "status": "failed", "currentIssue": "{issueKey}", "blocker": "..."}`
>
> **On completion:**
> Return:
> `{"repo": "{repoName}", "status": "complete", "completedIssues": [...], "gapIssuesCreated": [...]}`

### 3.2 Monitor Coder Tasks and handle restarts

After spawning all Coder Tasks, monitor their progress. Apply the Subagent Monitoring Policy throughout this phase.

For each result returned:
- `status: complete` → mark repo group `status: complete` in state; record `gapIssuesCreated`
- `status: context_exhausted` → apply Restart Protocol; spawn new Coder Task with `resumeFrom` set to current Jira step label; increment `coderTaskRestarts` counter for this group
- `status: failed` → log blocker, mark repo group `status: blocked`, create a Jira issue for the blocker

**GUARD: If a repo group's `coderTaskRestarts` exceeds 5, escalate:**
- Post a comment on the epic in Jira with the blocker details
- Mark the group `status: escalated`
- Continue with other repo groups
- Log: `WARNING: Repo group {repoName} has been restarted 5 times — escalating to human review`

Commit state after each group result:

```bash
cd $TENANT_DOCS_PATH && git pull --rebase && git add operations/agent-state/ && git commit -m "chore: epic-manager $ARGUMENTS.epic phase-3 {repo}-group done [$(git config user.email)]" && git push
```

### 3.3 Handle newly discovered gap issues

After all Coder Tasks complete, collect all `gapIssuesCreated` from their reports. For each gap issue:
1. If it has `parent = $ARGUMENTS.epic` → add to the appropriate repo group in state and loop Phase 3 for those issues
2. If it belongs to a different epic → record in `crossEpicIssues` in state; add a comment on the epic issue linking it

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.epic", "body": "Cross-epic issue discovered during implementation: {gapIssueKey} — {summary}. Linked to correct epic."}'
```

### 3.4 Loop if new issues remain

If any repo group has new issues added from gap discovery (step 3.3), loop Phase 3 for only those groups. Repeat until no new gap issues are added and all groups are `complete` or `escalated`.

If any groups are still `pending` or `blocked` after all Tasks return and restarts are exhausted, log the status and continue to Phase 4 with the completed issues.

Mark Phase 3 TodoWrite item as completed when all non-escalated groups are `complete`.

---

## Phase 4: Validate All Issues

Mark Phase 4 TodoWrite item as in_progress.

### **GUARD: Skip if `validateAllDone: true` in state**

### 4.1 Collect all issues to validate

Query Jira for all issues belonging to this epic that are in Validation or Done status:

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${PROJECT_KEY} AND (\"Epic Link\" = $ARGUMENTS.epic OR parent = $ARGUMENTS.epic) AND ((status = Validation) OR (status = Done AND labels not in (outcome:validated)))", "fields": ["key", "summary", "status"], "max_results": 100}'
```

Also include gap issues created during Phase 3 that are in Validation status.

### 4.2 Run /validate on each issue (parallel where safe)

Issues in Validation status can be validated in parallel if they are in different repos. Issues in the same repo must be validated serially to avoid environment conflicts.

For each group of issues by repo, spawn a Validator Task:

Spawn a Task subagent with model: sonnet. Provide this prompt:

> You are a Validator agent checking deployment and validation for issues in {repoName} for epic $ARGUMENTS.epic.
>
> Issues to validate (in this order):
> {issueList — key and summary}
>
> For each issue, run the /validate command:
> ```
> Skill(name="validate", arguments="{issueKey}")
> ```
>
> After /validate completes, check the Jira status:
> ```bash
> npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "{issueKey}", "fields": ["status", "labels"]}'
> ```
>
> Classify the result:
> - Issue transitions to Done → validation passed
> - Issue returns to To Do (outcome:failure-validation) → validation failed
> - Issue gets outcome:needs-human → needs human review
>
> **Unintended effects check:**
> After validating each issue, verify no unintended effects on other features:
> - Check that pipelines for related repos are still passing
> - Confirm that shared endpoints/types are behaving correctly in dev
>
> **E2E Verdict Requirement for Validator Tasks:**
> After `/validate` completes for each issue, call `/e2e-interpret {issueKey}` and include
> `E2E_VERDICT` in the result JSON. A FAIL `e2eVerdict` overrides any passing validate verdict.
> The orchestrator reads `e2eVerdict` directly and inspects artifact screenshots before
> accepting a PASS verdict. File sizes are NOT a signal — read the image content.
>
> Return JSON only:
> ```json
> {
>   "repo": "{repoName}",
>   "results": [
>     {"issue": "PROJ-XXX", "status": "passed", "e2eVerdict": "PASS"},
>     {"issue": "PROJ-YYY", "status": "failed", "reason": "...", "e2eVerdict": "FAIL"},
>     {"issue": "PROJ-ZZZ", "status": "needs-human", "reason": "...", "e2eVerdict": "BLOCKED"}
>   ]
> }
> ```

Monitor Validator Tasks and apply the Subagent Monitoring Policy if any become unresponsive. Restart using the same prompt.

### 4.3 Process validation results

Record all results in `validationResults` in state:

```json
"validationResults": {
  "PROJ-XXX": "passed",
  "PROJ-YYY": "failed",
  "PROJ-ZZZ": "needs-human"
}
```

Commit state:

```bash
cd $TENANT_DOCS_PATH && git pull --rebase && git add operations/agent-state/ && git commit -m "chore: epic-manager $ARGUMENTS.epic phase-4 validation-results [$(git config user.email)]" && git push
```

### 4.4 Re-work failed validations

For each issue with status `failed`:

1. Log: `Issue {issueKey} failed validation. Re-running /work workflow.`
2. Add it back to the appropriate repo group's issue list in state
3. Reset the repo group status to `pending`
4. Return to Phase 3 for that repo group only (run the full `/work → /review → /fix-pr → /resolve-pr` workflow)
5. After Phase 3 completes for that group, re-run Phase 4 for the re-worked issues

**GUARD: If an issue fails validation more than 3 times:**
- Transition the issue's Jira label to `outcome:needs-human`
- Post a Jira comment:
  ```bash
  npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "{issueKey}", "body": "Validation failed 3 times. Human review required. Last failure: {reason}."}'
  ```
- Record in state and continue with other issues (do NOT block the epic on this issue)

For each issue with status `needs-human`:
- Post a Jira comment summarizing what needs human review
- Record in state; do NOT block the epic

### 4.5 Confirm no unintended effects

After all issues pass validation, run a final cross-check:

Spawn a Task subagent with model: sonnet. Provide this prompt:

> Perform a final cross-check for unintended side effects after completing all issues in epic $ARGUMENTS.epic.
>
> Issues worked in this epic: {completedIssueList}
> Repos touched: {repoList}
>
> Check the following:
> 1. Query Jira for any issues in other epics that have been unexpectedly transitioned or labeled:
>    ```bash
>    npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${PROJECT_KEY} AND updated >= -1d AND \"Epic Link\" != $ARGUMENTS.epic AND parent != $ARGUMENTS.epic AND status changed AFTER -1d", "fields": ["key", "summary", "status", "labels"]}'
>    ```
> 2. List recent Concourse pipeline builds for touched repos and check for unexpected failures:
>    ```bash
>    npx tsx ~/.claude/skills/ci/list_builds.ts '{"pipeline": "{repoName}", "limit": 5}'
>    ```
>    Check each touched repo.
>
> Return JSON:
> ```json
> {
>   "unintendedEffectsFound": true/false,
>   "issues": [{"description": "...", "affectedIssue": "PROJ-XXX or null", "severity": "high/medium/low"}]
> }
> ```

If `unintendedEffectsFound: true`:
- For high severity: create Jira issues for each unintended effect, link to the originating epic issue
- For medium/low: post a warning comment on the epic
- Record in state

Set `validateAllDone: true`. Commit.

Mark Phase 4 TodoWrite item as completed.

---

## Phase 4.5: Epic Reflection

Mark Phase 4.5 TodoWrite item as in_progress.

### 4.5.1 Collect AgentDB episodes from /work subagents

```bash
npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts '{"task": "epic $ARGUMENTS.epic work implementation issues completed done", "k": 50, "threshold": 0.5}'
```

Also retrieve per-issue episodes for each completed issue key:

```bash
npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts '{"task": "work {issueKey} implementation pr merged", "k": 5, "threshold": 0.5}'
```

Collect all returned episodes into a combined context. Remove duplicates by episode ID.

### 4.5.2 Spawn Reflection Task

Spawn a Task subagent with model: opus. Provide this prompt:

> You are a senior engineer writing a post-implementation retrospective for epic $ARGUMENTS.epic.
>
> AgentDB episodes from all /work subagents during this epic:
> {combined episodes JSON}
>
> Epic PRP (if available): {prpContent or "not available"}
> Issues completed: {issueList}
> Issues requiring human review: {needsHumanList or "none"}
> Gaps found by architect review: {gapIssueList}
> Cross-epic issues created: {crossEpicIssues or "none"}
> Validation failures encountered: {failedValidationList}
> Unintended effects found: {unintendedEffectsList or "none"}
> Coder Task restarts: {coderTaskRestarts summary per repo}
>
> Write a reflection document in this EXACT format — include the frontmatter:
>
> ```
> ---
> title: "Epic $ARGUMENTS.epic Reflection"
> status: evergreen
> type: reference
> domain: platform
> ---
>
> # Epic $ARGUMENTS.epic Reflection
>
> ## Implementation Gaps
> [functionality harder or different than PRP described]
>
> ## Test Coverage Weaknesses
> [areas where test coverage was thin or missing]
>
> ## Recurring Blockers
> [patterns that slowed /work agents: CI failures, unclear AC, subagent restarts, etc.]
>
> ## Cross-Epic Risks
> [impacts on other epics, both caught and missed]
>
> ## Unintended Effects
> [any regressions or side effects discovered during validation]
>
> ## Subagent Reliability
> [patterns around context exhaustion, restarts, and how to improve prompts for future epics]
>
> ## Recommendations for Future Cycles
> - [concrete, actionable — e.g. "Add X to architect review checklist"]
> - [...]
> ```
>
> Return the full markdown text including frontmatter.

### 4.5.3 Write reflection to project-docs

Write the returned content to:
`$TENANT_DOCS_PATH/operations/agent-state/${CYCLE_KEY}/${GIT_USER_EMAIL}/epic-$ARGUMENTS.epic-reflection.md`

### 4.5.4 Post reflection summary to Jira

Post the Recommendations section (only) as a Jira comment:

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.epic", "body": "## Epic Reflection — Recommendations\n\n{recommendations from reflection}\n\nFull reflection: project-docs/operations/agent-state/{cycleKey}/{user}/epic-$ARGUMENTS.epic-reflection.md"}'
```

### 4.5.5 Cost Tracking Aggregation

Aggregate cost and token usage across all issues worked in this epic.

1. For each completed issue, query AgentDB for cost metrics:
```bash
npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts '{"task": "metrics-hourly {issueKey} cost tokens", "k": 10, "threshold": 0.3}'
```

2. Extract token usage and estimated cost from returned episodes. Sum per issue:
   - `tokens_in`: total input tokens
   - `tokens_out`: total output tokens
   - `estimated_cost`: total estimated cost (USD)

3. Compute epic totals across all issues.

4. Update state file with cost summary:
```json
"cost_summary": {
  "per_issue": {
    "PROJ-XXX": {"tokens_in": 0, "tokens_out": 0, "estimated_cost": 0.0},
    "PROJ-YYY": {"tokens_in": 0, "tokens_out": 0, "estimated_cost": 0.0}
  },
  "total_tokens_in": 0,
  "total_tokens_out": 0,
  "total_cost": 0.0,
  "issue_count": 0,
  "avg_cost_per_issue": 0.0
}
```

5. Include cost summary in the Jira epic completion comment (Phase 5.3):
   - Total tokens used
   - Total estimated cost
   - Average cost per issue
   - Most expensive issue

### 4.5.6 Store in AgentDB and commit

```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{"session_id": "${TENANT_NAMESPACE}", "task": "epic-reflection-$ARGUMENTS.epic", "reward": 0.9, "success": true, "critique": "{top 2 recommendations from reflection}"}'
```

```bash
cd $TENANT_DOCS_PATH && git pull --rebase && git add operations/agent-state/ && git commit -m "feat: epic-manager $ARGUMENTS.epic reflection committed [$(git config user.email)]" && git push
```

Mark Phase 4.5 TodoWrite item as completed.

---

## Phase 5: Close Epic

Mark Phase 5 TodoWrite item as in_progress.

### 5.1 Final child issue check

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${PROJECT_KEY} AND (\"Epic Link\" = $ARGUMENTS.epic OR parent = $ARGUMENTS.epic) AND status != Done", "fields": ["key", "summary", "status", "labels"], "max_results": 50}'
```

If any issues are not Done:
- Issues with `outcome:needs-human` → log warning; note them in the completion comment but do not block epic close
- Any other non-Done issues → log warning; do not close the epic; post summary comment and return `status: incomplete` to caller

### 5.1.5 outcome:validated Hard Gate

Check for Done issues lacking validation evidence:

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${PROJECT_KEY} AND (\"Epic Link\" = $ARGUMENTS.epic OR parent = $ARGUMENTS.epic) AND status = Done AND labels not in (outcome:validated) AND labels not in (outcome:needs-human, outcome:wont-do)", "fields": ["key", "summary", "status", "labels"], "max_results": 50}'
```

**HARD GATE: If any Done issues lack outcome:validated (excluding needs-human, outcome:wont-do):**
- Log: `BLOCKING EPIC CLOSE: {count} Done issues lack outcome:validated evidence`
- List each issue: `- {issueKey}: {summary} (status: Done, missing outcome:validated)`
- **DO NOT close the epic**
- Post comment on epic: "Epic close blocked - {count} Done issues require validation. Run /validate on each issue first."
- Loop back to Phase 4 for missing validation
- Return `status: incomplete` to caller

**If all Done issues have outcome:validated or exempt labels:**
- Log: `outcome:validated gate passed - all Done issues have validation evidence`
- Continue to epic transition


### 5.1.6 State Self-Consistency Guard

Verify state integrity before epic close:

```bash
# Check final state consistency
notDoneCount=$(npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${PROJECT_KEY} AND (\"Epic Link\" = $ARGUMENTS.epic OR parent = $ARGUMENTS.epic) AND status != Done AND labels not in (outcome:needs-human, outcome:wont-do)", "fields": ["key"], "max_results": 1}' | jq '.issues | length')
```

**CONSISTENCY ASSERTIONS (MANDATORY):**

1. **Assert notDoneCount == 0 or all remaining have exempt labels**
   - If `notDoneCount > 0`: FAIL - Epic cannot close with non-Done issues
   - Log: `CONSISTENCY FAILURE: {notDoneCount} issues remain non-Done without exempt labels`

2. **Assert validateAllDone: true in state**
   - If `state.validateAllDone != true`: FAIL - Phase 4 validation not completed
   - Log: `CONSISTENCY FAILURE: validateAllDone is false - Phase 4 incomplete`

3. **Assert no suspectDoneIssues remain unresolved**
   - If `state.suspectDoneIssues.length > 0`: FAIL - Phase 1.5 audit incomplete
   - Log: `CONSISTENCY FAILURE: {count} suspectDoneIssues remain unaudited`

4. **Final state integrity check**
   - Verify `epicClosed: false` in current state (should not be true yet)
   - If any assertion fails: DO NOT set `epicClosed: true`

**If ANY assertion fails:**
- Log: `STATE CONSISTENCY VIOLATION - Epic close aborted`
- Post comment on epic with assertion failures
- Return `status: consistency-violation` to caller
- **DO NOT transition epic to Done**

**If all assertions pass:**
- Log: `State consistency verified - proceeding with epic close`
- Set `epicClosed: true` in state
- Continue to epic transition


### 5.2 Transition epic to Done

First list available transitions:

```bash
npx tsx ~/.claude/skills/issues/list_transitions.ts '{"issue_key": "$ARGUMENTS.epic"}'
```

Parse the response to find the transition where `to.name` equals `"Done"`. If no `"Done"` transition, try `"Closed"`. If neither exists, log all available transitions and stop.

```bash
npx tsx ~/.claude/skills/issues/transition_issue.ts '{"issue_key": "$ARGUMENTS.epic", "transition_id": "{found-transition-id}"}'
```

### 5.3 Post completion comment

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.epic", "body": "## Epic Complete\n\n**Issues completed:** {count}\n**Gap issues found and addressed:** {gapIssueList or \"none\"}\n**Cross-epic issues created:** {crossEpicIssues or \"none\"}\n**Issues requiring human follow-up:** {needsHumanList or \"none\"}\n**Unintended effects found and addressed:** {unintendedEffectCount or \"none\"}\n**Subagent restarts required:** {totalRestarts}\n**Cost summary:** {total_tokens_in + total_tokens_out} tokens, ~${total_cost} USD (avg ${avg_cost_per_issue}/issue)\n\nAll changes deployed to dev. Validation passed. Reflection posted above."}'
```

### 5.3.5 Write Epic Closed Summary Document

Create comprehensive summary for project-docs:

```bash
CLOSED_SUMMARY_PATH="$TENANT_DOCS_PATH/operations/agent-state/${CYCLE_KEY}/${GIT_USER_EMAIL}/${CYCLE_KEY}-$ARGUMENTS.epic-closed-summary.md"
```

Write summary document:

```bash
cat > "$CLOSED_SUMMARY_PATH" << SUMMARY_EOF
---
title: "Epic $ARGUMENTS.epic Closed Summary"
status: reference
type: completion-report
domain: workflow
epic: "$ARGUMENTS.epic"
cycle: "${CYCLE_KEY}"
closedAt: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
---

# Epic $ARGUMENTS.epic Closed Summary

## Validation Status
- **Issues completed:** {completedIssueCount}
- **Issues with outcome:validated:** {validatedIssueCount}
- **Suspect Done issues found:** {suspectDoneCount}
- **Issues re-opened during audit:** {reopenedIssueCount}

## Issues Processed

### Completed Issues
{completedIssueList}

### Re-opened During Phase 1.5 Audit
{reopenedIssueList or "None"}

### Gap Issues Created
{gapIssueList or "None"}

### Issues Requiring Human Review
{needsHumanList or "None"}

## Validation Gaps Found
- **Built-but-not-wired components:** {builtNotWiredCount}
- **Code integration failures:** {integrationFailureCount}
- **Dead code detected:** {deadCodeCount}

## Summary
Epic $ARGUMENTS.epic closed successfully with enhanced validation. 
Phase 1.5 code integration audit identified and resolved {auditIssueCount} suspect Done issues.
All remaining issues have proper outcome:validated evidence.

SUMMARY_EOF
```


### 5.4 Commit final state and push

```bash
cd $TENANT_DOCS_PATH && git pull --rebase && git add operations/agent-state/ && git commit -m "feat: epic-manager $ARGUMENTS.epic complete — {completedIssueCount} issues, {validatedIssueCount} validated, {suspectDoneCount} suspect audited [$(git config user.email)]" && git push
```

### 5.5 Store completion in AgentDB

```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{"session_id": "${TENANT_NAMESPACE}", "task": "epic-manager-$ARGUMENTS.epic-complete", "reward": 1.0, "success": true, "critique": "Epic complete. Issues: {count}. Gaps: {gapCount}. Restarts: {totalRestarts}. Unintended effects: {unintendedEffectCount}."}'
```

Mark Phase 5 TodoWrite item as completed.

---

## Completion Signal

Return to caller (product manager Task or user):

```
Epic Manager: $ARGUMENTS.epic COMPLETE

Issues completed:           {list}
Gap issues created:         {list or "none"}
Cross-epic issues:          {list or "none"}
Needs-human issues:         {list or "none"}
Unintended effects found:   {count or "none"}
Subagent restarts:          {totalRestarts}
Cost:                       {total_tokens_in + total_tokens_out} tokens, ~${total_cost} USD
Validation:                 all passed (except needs-human items noted above)
Epic status:                Done (confirmed in Jira)
Reflection:                 project-docs/operations/agent-state/{cycle}/{user}/epic-$ARGUMENTS.epic-reflection.md
```

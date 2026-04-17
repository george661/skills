<!-- MODEL_TIER: opus (orchestrator) -->
---
description: Implement a Jira issue through PR merge (use /validate after deployment)
arguments:
  - name: issue
    description: Jira issue key (e.g., PROJ-123)
    required: true
  - name: --team
    description: Run as agent team with parallel planning, implementation, monitoring, and review
    required: false
---

## Agent Team Mode

**If `--team` flag is present**, load team definition from `.claude/teams/work.yaml` and create an agent team:

```
Create an agent team using the work-team definition from .claude/teams/work.yaml.
The issue to work is: $ARGUMENTS.issue
```

**If `--team` flag is NOT present**, continue with single-session orchestration below.

# Work on Jira Issue: $ARGUMENTS.issue

You are an **orchestrator**. Your job is to dispatch sub-commands and check their results.
**DO NOT do implementation, planning, or code review work yourself.**
Each sub-command is self-contained — it knows what to do. You just run them in order.

---

## How to Dispatch Sub-Commands

### Dispatch Routing (config-driven)

Inline vs dispatch routing is driven by `~/.claude/config/dispatch-routing.default.json`
(or tenant override at `$PROJECT_ROOT/.claude/config/dispatch-routing.json`).

Before dispatching any command, load the routing config:

```bash
# Resolve dispatch routing config
ROUTING_FILE=""
for candidate in \
  "$PROJECT_ROOT/.claude/config/dispatch-routing.json" \
  "$HOME/.claude/config/dispatch-routing.json" \
  "$HOME/.claude/config/dispatch-routing.default.json"; do
  [ -f "$candidate" ] && ROUTING_FILE="$candidate" && break
done

is_inline() {
  local cmd="$1"
  [ -z "$ROUTING_FILE" ] && return 1
  python3 -c "
import json, sys
data = json.load(open('$ROUTING_FILE'))
sys.exit(0 if any(e['command'] == '$cmd' for e in data.get('inline', [])) else 1)
"
}
```

Default inline commands (from `dispatch-routing.default.json`):
- `create-implementation-plan` — local models misidentify current state
- `review-implementation-plan` — MODEL_TIER: opus quality gate
- `review` — MODEL_TIER: opus quality gate
- `resolve-pr` — short, high-stakes merge operation

Tenants override by adding `.claude/config/dispatch-routing.json` to their tenant-agents repo.

**ALL other sub-commands MUST be dispatched via `dispatch-local.sh`**, regardless of
what `resolve-model.py` returns. This prevents the orchestrator from accidentally
running implementation/planning work on Opus when `model-routing.json` is misconfigured.

### Dispatch Procedure

Resolve the model for each command, then dispatch accordingly:

```bash
eval $(python3 ~/.claude/hooks/resolve-model.py <command-name> --env)
```

- If `is_inline "<command-name>"` returns 0 (true): run inline via slash command
- Otherwise: ALWAYS dispatch via dispatch-local.sh

`dispatch-local.sh` handles everything: env vars, AWS/Jira/Bitbucket creds, Ollama config,
prompt enrichment (e.g. pre-fetching PR comments for fix-pr), progress display,
and result extraction. It is the **single source of truth** — the same script is
used by the `route-slash-command.py` hook when intercepting Skill/SlashCommand calls.

**Do NOT construct env -i / claude subprocess commands manually.** Always use dispatch-local.sh.

**IMPORTANT dispatch rules:**
- **Set timeout to 900000** (15 minutes) on each dispatch Bash call
- **Do NOT use run_in_background** — you must wait for the result before proceeding
- Read the output before moving to the next phase — the output contains repo name, PR number, etc. needed for subsequent phases

---

## Phase 0: Resume Check

```bash
# Check orchestrator-namespaced checkpoints (orch.phase*)
checkpoint=$(python3 ~/.claude/hooks/checkpoint.py load $ARGUMENTS.issue 2>/dev/null || echo '{"found":false}')
```

If checkpoint found with a completed `orch.*` phase, skip to the next incomplete phase.
Orchestrator phases use `orch.` prefix to avoid collision with agent checkpoints.

**Phase name mapping:**
- `orch.phase0.5-complete` → Prior work assessed (contains `resume_path` and context), skip to indicated phase
- `orch.phase1-complete` → Planning done, skip to Phase 1.5
- `orch.phase1.5-complete` → Plan approved, skip to Phase 2
- `orch.phase2-complete` → PR created (contains `repo` and `pr_number`), skip to Phase 3

---

## Phase 0.1: Git Sync Gate (MANDATORY)

**HARD GATE — cannot proceed without sync.**

Before any branching or worktree creation, ensure local main is current:

```bash
cd $PROJECT_ROOT/<repo>
git fetch origin main
LOCAL=$(git rev-parse main 2>/dev/null || echo "none")
REMOTE=$(git rev-parse origin/main 2>/dev/null || echo "none")
if [ "$LOCAL" != "$REMOTE" ]; then
  echo "Local main is behind origin/main. Syncing..."
  git checkout main && git pull origin main
  echo "Synced. Local main now at $(git rev-parse --short main)"
fi
```

If `git fetch` fails (network, auth): **STOP. Report failure. Do not proceed.**

---

## Phase 0.2: Repo Context Loading (MANDATORY)

1. Determine target repository from issue description or labels.

2. Check CGC index freshness:
   - If repo not indexed OR index older than 24 hours: `mcp__CodeGraphContext__add_code_to_graph` for the repo
   - If CGC unavailable: log warning, proceed without CGC (structural checks degrade to manual)

3. Read repository documentation:
   ```bash
   REPO_PATH=$PROJECT_ROOT/<repo>
   cat $REPO_PATH/CLAUDE.md 2>/dev/null || echo "WARNING: CLAUDE.md missing"
   cat $REPO_PATH/TESTING.md 2>/dev/null || echo "WARNING: TESTING.md missing"
   cat $REPO_PATH/VALIDATION.md 2>/dev/null || echo "WARNING: VALIDATION.md missing"
   ```

4. Extract and store as structured context for subcommands:
   - Pre-commit requirements from TESTING.md "Pre-Commit Checklist" section
   - Evidence requirements from VALIDATION.md "Evidence Requirements" section
   - Validation profile from CLAUDE.md "Validation Profile" section

5. If any file is missing: create a Jira issue to add it (use `/issue` skill), then proceed with available docs.

6. Pass extracted context to all subsequent phases via checkpoint state.

---



## Phase 0.5: Prior Work Assessment (INLINE — Opus)

This runs inline. Do NOT dispatch. Costs ~300 tokens.

**Purpose:** Detect whether this issue has been through prior work cycles and route to the
correct resume point instead of starting from scratch.

### Step 1: Read Jira labels and status

```bash
issue=$(npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "status,labels,comment"}')
labels=$(echo "$issue" | jq -r '.fields.labels // []')
status=$(echo "$issue" | jq -r '.fields.status.name')
```

### Step 2: Detect prior work signals

Check labels for these signals (in priority order):

| Signal | Labels | Meaning |
|--------|--------|---------|
| PR exists | `pr:<repo>/<number>` | A PR was created in a prior run |
| Validation failed | `outcome:validation-failed` | Went through full pipeline, validation rejected it |
| Validation skipped | `outcome:validation-skipped` | Validation was skipped due to process issue (e.g. stale review verdict), not code defect |
| Rework needed | Code review comment with `REQUIRES REWORK` | Review found issues that need fixing |
| Plan created | `outcome:success-plan-created` | Plan was approved but implementation didn't complete |

### Step 3: If prior work detected, read Jira comments for context

Extract from comments (scan in reverse chronological order):
- **Most recent code review verdict** — look for `### Verdict:` or `**Code Review:`
- **Most recent validation report** — look for `## Validation Report`
- **Most recent implementation plan** — look for `## Implementation Plan` or `## REVISED IMPLEMENTATION PLAN`
- **Failure reasons** — specific issues cited in review/validation

### Step 4: Route to resume path

| Condition | Resume Path | Action |
|-----------|-------------|--------|
| PR exists + merged + `outcome:validation-skipped` | **Verify code first** | Validation was skipped (process issue, not code defect). Before re-planning, run a quick build/test check on main to see if the code is actually correct. If it passes, skip to close-out (transition to VALIDATION, no new PR needed). If it fails, fall through to re-plan. |
| PR exists + merged + `outcome:validation-failed` | **Phase 1 (Re-plan)** | Need new branch on top of merged work. Pass validation failure context to `/create-implementation-plan` as `--rework-context` |
| PR exists + open + review REQUIRES REWORK | **Phase 4 (Fix PR)** | Skip planning/implementation. Extract repo + PR from labels, dispatch `/fix-pr` with review issues as `--unresolved` context |
| PR exists + open + no review or review APPROVED | **Phase 3 (Review)** | PR exists but wasn't reviewed or review passed. Resume from review |
| PR exists + merged + validation failed (deploy issue) | **Re-validate** | Code is fine, just needs redeployment. Tell user to run `/validate` instead |
| Plan created + no PR | **Phase 2 (Implement)** | Plan approved but implementation didn't finish. Resume from implementation |
| No prior work signals | **Phase 1 (Fresh start)** | Normal flow |

### Step 5: Clean up stale labels

Before proceeding, remove stale outcome/step labels from prior attempts:
```bash
# Read current labels, remove stale ones, keep structural labels (repo-*, pr:*, tier-*, domain-*)
current_labels=$(echo "$issue" | jq -r '[.fields.labels[] | select(startswith("outcome:") or startswith("step:") | not)]')
npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "$ARGUMENTS.issue", "labels": <cleaned labels array>}'
```

### Step 6: Save checkpoint and proceed

```bash
python3 ~/.claude/hooks/checkpoint.py save $ARGUMENTS.issue orch.phase0.5-complete '{"resume_path":"<phase>","repo":"<repo>","pr_number":<num>,"rework_context":"<summary of issues from prior attempt>"}'
```

**Then jump to the indicated resume phase.** Do NOT fall through to Phase 1 if a resume
path was determined.

---

## Phase 0.7: Bug Test Verification (MANDATORY for Bug issue types)

**Only runs when the issue type is Bug.** Skip for Stories, Tasks, and other types.

```bash
issue_type=$(echo "$issue" | jq -r '.fields.issuetype.name')
if [ "$issue_type" != "Bug" ]; then
  echo "[phase 0.7] Not a bug — skipping test verification"
  # proceed to Phase 1
fi
```

### Step 1: Check for pre-existing failing test branches

Search for remote branches matching this bug's issue key (created by `/bug` Phase 6.2):

```bash
FOUND_TEST_BRANCHES=""
for repo_dir in $PROJECT_ROOT/*/; do
  [ -d "$repo_dir/.git" ] || continue
  repo_name=$(basename "$repo_dir")
  cd "$repo_dir"
  git fetch origin
  branch=$(git branch -r --list "origin/$ARGUMENTS.issue-failing-tests" 2>/dev/null | tr -d ' ')
  if [ -n "$branch" ]; then
    echo "Found failing test branch in $repo_name: $branch"
    FOUND_TEST_BRANCHES="$FOUND_TEST_BRANCHES $repo_name"
  fi
done
```

### Step 2a: Failing tests exist — verify they still fail

If branches were found from `/bug`:

1. Create worktrees from those branches:
   ```bash
   cd $PROJECT_ROOT/<repo>
   git worktree add $PROJECT_ROOT/worktrees/<repo>/$ARGUMENTS.issue-test-verify -b $ARGUMENTS.issue-test-verify origin/$ARGUMENTS.issue-failing-tests
   cd $PROJECT_ROOT/worktrees/<repo>/$ARGUMENTS.issue-test-verify
   npm install 2>/dev/null || go mod download 2>/dev/null || true
   ```

2. Run ONLY the tests from the failing-tests branch (not the full suite):
   - Read the Jira comment from `/bug` Phase 6.2 for test file paths
   - Run those specific tests

3. **Verify tests still fail for expected reasons:**
   - If they FAIL as expected: the bug is confirmed still present — proceed to Phase 1
   - If they PASS: the bug may have been inadvertently fixed by another change. Investigate
     and report to user before continuing.

4. Clean up the verify worktree (the actual fix will happen on the implementation branch):
   ```bash
   cd $PROJECT_ROOT/<repo>
   git worktree remove $PROJECT_ROOT/worktrees/<repo>/$ARGUMENTS.issue-test-verify --force
   ```

### Step 2b: No failing tests exist — backfill (MANDATORY)

If no test branches exist for this bug, the tests must be created before implementation begins.
This handles bugs created before the test-first workflow was introduced.

1. Read the bug's description, reproduction steps, and root cause hypothesis from Jira
2. Determine affected repos and test types (same logic as `/bug` Phase 6.2 Step 1)
3. Create worktrees:
   ```bash
   cd $PROJECT_ROOT/<repo>
   git fetch origin main
   git worktree add $PROJECT_ROOT/worktrees/<repo>/$ARGUMENTS.issue-failing-tests -b $ARGUMENTS.issue-failing-tests origin/main
   ```
4. Write failing tests, run them, verify expected failure
5. Commit with smart commits and push:
   ```bash
   cd $PROJECT_ROOT/worktrees/<repo>/$ARGUMENTS.issue-failing-tests
   git add -A
   git commit -m "$ARGUMENTS.issue add failing regression test (backfill)

   Test asserts correct behavior that is currently broken.
   Expected to pass once $ARGUMENTS.issue is resolved."
   git push -u origin $ARGUMENTS.issue-failing-tests
   ```
6. Add Jira comment documenting the backfilled tests (same format as `/bug` Phase 6.2 Step 6)

### Step 3: Regression traceability check

Verify the bug has proper Jira links for regression traceability:

```bash
links=$(echo "$issue" | jq -r '.fields.issuelinks // []')
has_cause_link=$(echo "$links" | jq '[.[] | select(.type.name == "Problem/Incident" or .type.name == "Relates")] | length')
```

If `has_cause_link == 0` AND the bug description references another issue key:
1. Search for the original issue
2. Create an appropriate Jira issue link (`Relates` or `Problem/Incident` for regressions)
3. If the original issue has a parent epic, link the bug to the epic too

### Step 4: Pass test context to planning

Store the test locations so `/create-implementation-plan` knows the acceptance criteria:

```bash
python3 ~/.claude/hooks/checkpoint.py save $ARGUMENTS.issue orch.phase0.7-complete '{
  "bug_tests": [{"repo": "<repo>", "branch": "$ARGUMENTS.issue-failing-tests", "test_file": "<path>", "expected_failure": "<description>"}],
  "regression_link": "<original-key or null>"
}'
```

The implementation plan MUST include:
- Cherry-picking or recreating the failing tests in the implementation branch
- Making those tests pass as part of the fix
- The PR must demonstrate: test was failing before fix, passes after fix

---

## Phase 1: Planning

**Skip this phase if Phase 0.5 determined a resume path other than "fresh start" or "re-plan".**

If Phase 0.5 route is **re-plan** (validation failed on merged PR), append the rework context
when running the planning command inline:

Run inline: `/create-implementation-plan $ARGUMENTS.issue --rework-context '<summary of validation failures and what needs to change>'`

**If this is a Bug issue AND Phase 0.7 produced test context**, pass it to the planning command:

Run inline: `/create-implementation-plan $ARGUMENTS.issue --bug-tests '<JSON from orch.phase0.7-complete checkpoint>'`

The implementation plan MUST include steps to:
1. Cherry-pick or recreate the failing regression tests in the implementation branch
2. Write the fix that makes those tests pass
3. Verify all pre-existing tests still pass alongside the new ones

```bash
# Worklog: record agent starting this issue
npx tsx ~/.claude/skills/jira/worklog_identity.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"phase\": \"starting\", \"command\": \"/work\", \"message\": \"Beginning implementation workflow\"}" 2>/dev/null || true
```

Run inline: `/create-implementation-plan $ARGUMENTS.issue`

Save checkpoint after completion:
```bash
python3 ~/.claude/hooks/checkpoint.py save $ARGUMENTS.issue orch.phase1-complete '{"status":"planned"}'
```

---

## Phase 1.5: Review Implementation Plan (MANDATORY quality gate)

This phase runs on Opus inline (not dispatched) to validate the plan before the local model spends 10-15 minutes implementing it.

Run inline: `/review-implementation-plan $ARGUMENTS.issue`

**IMPORTANT:** The review-implementation-plan skill posts the verdict to Jira automatically.
If running the review inline (not via skill), you MUST post the verdict to Jira as a comment
with heading "Implementation Plan Review" and "Verdict:" line BEFORE dispatching
`/fix-implementation-plan`. The fix command reads the verdict from Jira comments — if you
skip posting, the fix dispatch will fail with "No review verdict found."

**Decision based on verdict:**
- `APPROVED` → proceed to Phase 2
- `NEEDS_FIXES` → dispatch `/fix-implementation-plan $ARGUMENTS.issue`, then re-run `/review-implementation-plan $ARGUMENTS.issue` (max 2 fix cycles, then escalate to user)
- `REJECTED` → re-run inline `/create-implementation-plan $ARGUMENTS.issue` with review feedback appended, then loop back to Phase 1.5

Save checkpoint after approval:
```bash
python3 ~/.claude/hooks/checkpoint.py save $ARGUMENTS.issue orch.phase1.5-complete '{"status":"plan-approved"}'
```

---

## Phase 2: Implementation

Dispatch: `/implement $ARGUMENTS.issue`

**IMPORTANT:** `dispatch-local.sh` now auto-enriches `/implement` with worktree path, repo, branch,
and plan context from checkpoints + `.agent-context.json` + Jira comments. You do NOT need to manually
pass these as arguments. If the first dispatch still fails to find context, re-dispatch with explicit args:
```bash
~/.claude/hooks/dispatch-local.sh implement "$ARGUMENTS.issue --worktree <path> --repo <repo> --branch <branch>"
```

This creates a PR. Extract the repo and PR number from the output for Phase 3.

Save checkpoint:
```bash
python3 ~/.claude/hooks/checkpoint.py save $ARGUMENTS.issue orch.phase2-complete '{"status":"pr-created","repo":"<repo>","pr_number":<pr-number>}'
```

```bash
npx tsx ~/.claude/skills/jira/worklog_identity.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"phase\": \"completed\", \"command\": \"/work\", \"message\": \"PR created and review initiated\"}" 2>/dev/null || true
```

---

## Phase 3: Code Review (MANDATORY — run immediately, do not wait for CI)

Run inline (is_inline check passes — see dispatch routing config): `/review <repo> <pr-number>`

Use the repo and PR number from Phase 2's output.

### Phase 3b: Read Review Verdict (MANDATORY — do NOT skip)

After the review completes, **you MUST read the verdict from Jira** before deciding whether
to proceed to Phase 4 or Phase 5. Do NOT rely on your interpretation of the review output —
the Jira comment is the source of truth.

```bash
# Fetch the most recent review comment from Jira
issue=$(npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "comment"}')
# Find the most recent comment containing "### Verdict:" or "**Code Review:"
# Extract the verdict: APPROVED, REQUIRES REWORK, or LGTM
```

**Routing based on verdict:**
- `APPROVED` or `LGTM` → skip Phase 4, proceed to Phase 5 (Gate Check)
- `REQUIRES REWORK` → **MUST enter Phase 4** (Fix PR). Do NOT skip to merge.
- No verdict found → treat as needing review, re-run `/review`

**This check exists because:** In the PROJ-2451 incident, the orchestrator ran `/review`,
received REQUIRES REWORK, but skipped Phase 4 and proceeded to merge — causing a validation
failure that required a full rework cycle. The explicit verdict read prevents this.

---

## Phase 4: Fix Review Issues (MANDATORY when review verdict is REQUIRES REWORK)

Dispatch: `/fix-pr $ARGUMENTS.issue <repo> <pr-number>`

Use the repo and PR number extracted from Phase 2's output (same values used in Phase 3).

### Phase 4b: Post-Fix Verification (MANDATORY — do NOT skip)

After `/fix-pr` completes, the orchestrator MUST verify the fixes before proceeding.
Do NOT trust the local model's self-report. Run these checks yourself:

1. **Re-fetch the diff** to see what changed:
   ```bash
   npx tsx ~/.claude/skills/vcs/get_pull_request_diff.ts '{"repo": "<repo>", "pr_number": <num>}'
   ```

2. **Run the full test suite** (not just changed files):
   ```bash
   cd <worktree-path> && npm test 2>&1
   ```

3. **Run typecheck** if TypeScript:
   ```bash
   cd <worktree-path> && npx tsc --noEmit 2>&1
   ```

4. **Scan for regressions**: Check that every file the local model modified still has passing tests.
   Common local model failure: removes code but doesn't update corresponding tests.

5. **Residual scan** (MANDATORY after every fix-pr): Grep the changed file(s) for patterns
   the review flagged. Common local model residue:
   - Duplicate enum/type definitions (created new instead of extending existing)
   - Syntax placed on wrong line (e.g., `X AlternativeEvent` on its own line instead of
     appended to the `emits event` clause)
   - Wrong type (e.g., typed enum reference when plain int was specified)
   - Wrong initiator role in flows (e.g., "Admin" when "GlobalAdmin" was required)

   ```bash
   # Example: check for duplicate enum definitions
   grep -c "enum SignalCategory" domain/general-wisdom.cml  # should be 1, not 2
   ```

**If any check fails or unresolved comments remain:** Re-dispatch `/fix-pr` with the
`unresolved` argument listing the SPECIFIC issues still present. This prevents the local
model from re-discovering comments and missing the same ones again:

```bash
~/.claude/hooks/dispatch-local.sh fix-pr "$ARGUMENTS.issue <repo> <pr-number> --unresolved 'WARNING: <description of issue 1>' 'WARNING: <description of issue 2>'"
```

**For trivial fixes (< 5 lines) where the local model has already failed once:**
The orchestrator may fix directly and push, rather than burning another 5+ minute dispatch
cycle. This is an acceptable escape hatch for small, obvious corrections.

Repeat Phase 4 → 4b until all fixes are verified (max 3 cycles, then escalate to user).

---

### Phase 4c: Re-Review After Fixes (MANDATORY when Phase 4 was triggered)

**This phase exists because:** In the PROJ-4645 incident, `/fix-pr` pushed commits that addressed
all review findings, but the REQUIRES REWORK verdict from the original review remained as the
most recent review comment on Jira. When `/validate` ran, Phase 0.75 (code review blocker check)
saw the stale REQUIRES REWORK and short-circuited — even though the code was already fixed and
merged. This caused a wasted validation + rework cycle.

**After Phase 4b verification passes**, re-run the code review to produce a fresh verdict:

Run inline: `/review <repo> <pr-number>`

### Phase 4c.1: Read Re-Review Verdict

Same procedure as Phase 3b — read the verdict from Jira comments:

```bash
issue=$(npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "comment"}')
# Find the most recent comment containing "### Verdict:"
# Extract: APPROVED, REQUIRES REWORK, or LGTM
```

**Routing:**
- `APPROVED` or `LGTM` → proceed to Phase 5 (Gate Check)
- `REQUIRES REWORK` → return to Phase 4 (the fixes introduced new issues or missed something).
  Max 2 re-review cycles total, then escalate to user.

---

## Phase 5: Gate Check (MANDATORY CI validation)

### 5a: Wait for CI validation

Poll the Concourse PR job until it completes (max 15 minutes). Returns structured per-task output:

```bash
# Detect the PR validation job name
pr_job=$(fly -t ${CI_TARGET} jobs -p "<repo>" --json 2>/dev/null \
  | jq -r '[.[].name | select(test("^pr[-_]"; "i") or test("^validate[-_]?pr"; "i") or test("^check[-_]?pr"; "i"))] | first // empty')
[ -z "$pr_job" ] && pr_job="pr-check"

ci_result=$(cd $PROJECT_ROOT && npx tsx ~/.claude/skills/ci/wait_for_ci.ts \
  "{\"repo\": \"<repo>\", \"job\": \"$pr_job\", \"timeout_seconds\": 900}")

ci_success=$(echo "$ci_result" | jq -r '.success')
ci_status=$(echo "$ci_result"  | jq -r '.status')
ci_run=$(echo "$ci_result"     | jq -r '.run')
```

Print: `[CI] $ci_status — $ci_run`

**If the build failed (`ci_success` is `false`):**

1. Extract the specific failing tasks and their last log lines:
   ```bash
   failing_tasks=$(echo "$ci_result" | jq -r '
     .output | to_entries[]
     | select(.value.success == false)
     | "FAILED: \(.key)\n\(.value.logs[-5:] | join("\n"))"')
   echo "$failing_tasks"
   ```

2. Build the `--unresolved` argument from failing task names and log snippets,
   then re-dispatch `/fix-pr` with specific failure context (see Phase 4 for dispatch pattern).

3. Return to Phase 4 to fix the issue, then push and re-check.

**If the build timed out:**
- Check if a build is even running (PR may not have triggered one yet)
- If no build exists, proceed with a warning to the user

### 5b: Verify all conditions

- CI pipeline PASSED (from 5a)
- ALL critical/warning review comments addressed
- ALL questions answered
- Post-fix verification passed (Phase 4b)

If any condition fails, return to Phase 4.

---

## Phase 6: Merge

Run inline (is_inline check passes — see dispatch routing config): `/resolve-pr $ARGUMENTS.issue`

This runs on Opus because it's a short, high-stakes operation. Local models have failed
on the VCS merge API and fallen back to dangerous `git merge + git push` patterns.

---

## Phase 7: Verify and Done

### 7a: Verify Jira Status (MANDATORY — do NOT skip)

After `/resolve-pr` completes (whether dispatched or inline), the orchestrator MUST verify
the Jira issue was actually transitioned. Local models frequently crash during worktree
cleanup and skip the transition step.

```bash
# Check current Jira status
issue=$(npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "status"}')
status=$(echo "$issue" | jq -r '.fields.status.name')
```

**If status is NOT "VALIDATION":** Recover by transitioning inline:
```bash
npx tsx ~/.claude/skills/issues/list_transitions.ts '{"issue_key": "$ARGUMENTS.issue"}'
# Find the VALIDATION transition ID, then:
npx tsx ~/.claude/skills/issues/transition_issue.ts '{"issue_key": "$ARGUMENTS.issue", "transition_id": "<id>"}'
```

### 7b: Verify PR is Merged (MANDATORY)

```bash
pr=$(npx tsx ~/.claude/skills/vcs/get_pull_request.ts '{"repo": "<repo>", "pr_number": <num>}')
state=$(echo "$pr" | jq -r '.state')
```

**If state is NOT "MERGED":** Merge inline:
```bash
npx tsx ~/.claude/skills/vcs/merge_pull_request.ts '{"repo": "<repo>", "pr_number": <num>}'
```

### 7c: Print Summary, Key Lesson, and Store

**Print a workflow summary table** showing every phase, its result, and notable events:

```
## Work Complete: $ARGUMENTS.issue — PR merged to main.

| Phase | Result | Notes |
|-------|--------|-------|
| Planning | Done | <repo, worktree created> |
| Plan Review | <APPROVED or NEEDS_FIXES → APPROVED> | <what was caught, if anything> |
| Implementation | Done | PR #<num> created |
| Code Review | <PASSED or REQUIRES REWORK> | <N critical, M warnings, or "clean"> |
| Fix PR | <Done or N/A> | <what was fixed, if anything> |
| Re-Review | <APPROVED or N/A> | <fresh verdict after fixes> |
| CI Gate | PASSED | <build info> |
| Merge | MERGED | <commit hash> |
| Jira Status | VALIDATION | Transitioned |

### Key Lesson
<Classify before writing — only one applies:
- Bug/infrastructure issue → `Bug filed: <ISSUE-KEY> — <description>`
- Genuine reusable lesson → `Lesson stored: <one sentence>`
- Clean run → `Clean run, no issues.`>

After deployment, run: /validate $ARGUMENTS.issue
```

**After printing the summary, act on the finding:**

If it's a bug or infrastructure issue, file it:
```bash
~/.claude/hooks/dispatch-local.sh bug "<one-sentence description>"
```

If it's a genuine reusable lesson, derive a specific kebab-case `task_type` from the topic of the lesson — never use a generic value like `"work"`. Examples: `"testing-context-providers"`, `"go-lambda-iam-permissions"`, `"pact-contract-updates"`. Store it in AgentDB and use it as the episode critique:
```bash
npx tsx ~/.claude/skills/agentdb/pattern_store.ts "{\"task_type\": \"<kebab-case-topic>\", \"approach\": \"<lesson>\", \"success_rate\": 1.0}"
```

If it's a clean run, use `"critique": "Clean run, no issues."` in the episode below.

**Store episode:**
```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts "{\"session_id\": \"${TENANT_NAMESPACE}\", \"task\": \"/work $ARGUMENTS.issue\", \"input\": {}, \"output\": \"completed\", \"reward\": <0.0-1.0 based on how clean the run was>, \"success\": true, \"critique\": \"<the key lesson from above>\"}"
```

**Reward scoring guide:**
- `1.0` — Clean run, no fix cycles needed
- `0.8` — One fix cycle (plan fix or PR fix, not both)
- `0.6` — Multiple fix cycles or plan rejection + redo
- `0.4` — Required orchestrator intervention to unblock

### 7d: Cleanup Worktree and Update Main (MANDATORY — run last)

After everything else succeeds, clean up the worktree and pull the merged changes into main.
**Order matters:** cd out of the worktree FIRST, then remove it, then update main.

```bash
# 1. cd to the main repo (NEVER remove a worktree while cwd is inside it)
cd $PROJECT_ROOT/<repo>

# 2. Remove the worktree
git worktree remove $PROJECT_ROOT/worktrees/<repo>-$ARGUMENTS.issue --force 2>/dev/null || true

# 3. Delete the remote feature branch (Bitbucket may have already done this on merge)
git push origin --delete <branch-name> 2>/dev/null || true

# 4. Pull merged changes into main
git checkout main && git pull origin main
```

This ensures the local main branch has the merged commit and the worktree is cleaned up.

---

## Sub-Commands Reference

| Command | Purpose | Step Label |
|---------|---------|------------|
| `/create-implementation-plan` | Planning — creates plan and worktree | `step:planning` |
| `/review-implementation-plan` | Quality gate — Opus reviews plan before implementation | `step:planning` |
| `/fix-implementation-plan` | Fix plan issues identified by review | `step:planning` |
| `/implement` | Implementation — TDD, validation, PR creation | `step:implementing` → `step:awaiting-ci` |
| `/review` | Code review — inline comments and Jira summary | `step:reviewing` |
| `/fix-pr` | Fix CI or review issues | `step:fixing-pr` |
| `/resolve-pr` | Merge and cleanup | `step:merging` |
| `/validate` | Post-deployment validation | `step:validating` |

---

## Available Step Labels

| Label | Phase |
|-------|-------|
| `step:planning` | Implementation plan being created |
| `step:implementing` | Code being written (TDD cycle) |
| `step:awaiting-ci` | PR created, waiting for CI pipeline |
| `step:ready-for-review` | CI passed, PR ready for review |
| `step:reviewing` | PR under code review |
| `step:fixing-pr` | Addressing CI failures or review comments |
| `step:merging` | PR being merged |
| `step:validating` | Post-deployment validation |

### Querying by Step Label

```bash
# Find issues awaiting CI
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${TENANT_PROJECT} AND labels = \"step:awaiting-ci\"", "fields": ["key", "summary", "status"]}'

# Find issues ready for review
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${TENANT_PROJECT} AND labels = \"step:ready-for-review\"", "fields": ["key", "summary", "status"]}'
```

---

## Workflow Diagram

```
/work PROJ-123 (this orchestrator)
  │
  ├─► Phase 0: Resume from checkpoint (if any)
  │
  ├─► Phase 0.5: Prior Work Assessment (inline Opus)
  │     ├─ No prior work → Phase 0.7 (if Bug) or Phase 1 (fresh start)
  │     ├─ PR open + REQUIRES REWORK → Phase 4 (fix PR with review context)
  │     ├─ PR open + no review → Phase 3 (review)
  │     ├─ PR merged + validation-skipped → verify code on main, close-out if passing
  │     ├─ PR merged + validation-failed (code) → Phase 1 (re-plan with rework context)
  │     ├─ PR merged + validation-failed (deploy) → tell user to /validate
  │     └─ Plan created + no PR → Phase 2 (implement)
  │
  ├─► Phase 0.7: Bug Test Verification (Bug issues only)
  │     ├─ Failing tests found → verify still failing → Phase 1
  │     ├─ No tests found → backfill: create failing tests, commit, push → Phase 1
  │     └─ Not a Bug → skip to Phase 1
  │
  ├─► Phase 1: /create-implementation-plan PROJ-123
  │
  ├─► Phase 1.5: /review-implementation-plan PROJ-123  (Opus quality gate)
  │     ├─ APPROVED → continue
  │     ├─ NEEDS_FIXES → /fix-implementation-plan PROJ-123 → re-review (max 2 cycles)
  │     └─ REJECTED → re-run /create-implementation-plan with feedback
  │
  ├─► Phase 2: /implement PROJ-123
  │
  ├─► Phase 3: /review <repo> <pr-number>
  │     └─ REQUIRES REWORK → Phase 4
  │
  ├─► Phase 4: /fix-pr PROJ-123 <repo> <pr-number> (repeat until clean)
  │     └─ Phase 4c: Re-review → APPROVED → Phase 5
  │                             → REQUIRES REWORK → back to Phase 4 (max 2 cycles)
  │
  ├─► Phase 5: Gate check (CI passed + all comments addressed)
  │
  ├─► Phase 6: /resolve-pr PROJ-123
  │
  └─► Phase 7: Verify + /validate PROJ-123 (after deployment)
```

---

## Quick Reference

```bash
# Full automated workflow
/work PROJ-123

# Manual step-by-step
/create-implementation-plan PROJ-123
/review-implementation-plan PROJ-123       # Opus quality gate
/fix-implementation-plan PROJ-123          # if review found issues
/implement PROJ-123
/review lambda-functions 42
/fix-pr PROJ-123 lambda-functions 42  # if needed, pass repo + PR number
/resolve-pr PROJ-123
/validate PROJ-123        # after deployment
```

---

## Related Commands

| Command | Description |
|---------|-------------|
| `/next` | Find and start work on next priority issue |
| `/review <pr-url>` | Perform code review on any PR |
| `/bug <description>` | Report a bug with evidence collection |
| `/audit <url>` | Role-based UI compliance testing |

---

**START NOW: Run Phase 0, then Phase 0.5 (prior work assessment), then route to the appropriate phase.**

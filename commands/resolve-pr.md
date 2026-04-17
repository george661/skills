<!-- MODEL_TIER: sonnet -->
<!-- DISPATCH: Spawn a Task subagent with model: "sonnet" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Sonnet. -->

---
description: Triggered by successful PR build - merge PR, cleanup worktree, transition issue to Validate
arguments:
  - name: issue
    description: Jira issue key (e.g., PROJ-123)
    required: true
---

# Resolve PR: $ARGUMENTS.issue

## Purpose

This command handles successful CI pipeline completion:
- Verify CI pipeline passed (including Pact/Hurl tests)
- Merge the PR
- Cleanup worktree
- Transition issue to VALIDATION status
- Store validation criteria for /validate command

**Trigger:** CI pipeline PASSED on PR for $ARGUMENTS.issue
**Next step after this command:** After deployment completes, run `/validate $ARGUMENTS.issue`

---

## Step Label (MANDATORY)

At the START of this command, update the step label to `step:merging`:

```bash
issue=$(npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "labels"}')
labels=$(echo "$issue" | jq -r '.fields.labels // [] | map(select(startswith("step:") | not)) + ["step:merging"] | @json')
npx tsx ~/.claude/skills/issues/update_issue.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"labels\": $labels, \"notify_users\": false}"
```

---

## MANDATORY: Worktree + PR Workflow

> **⛔ CRITICAL REQUIREMENTS:**
>
> 1. **MUST be executed from the worktree** created by `/create-implementation-plan`
> 2. **This command merges the PR** and cleans up the worktree
> 3. **The `enforce-worktree.sh` hook will BLOCK** any attempt to modify files outside a worktree
> 4. **Worktree cleanup** is performed AFTER successful merge to main

**Worktree Context:**
- This command is triggered after CI passes on the PR
- The worktree contains all the implemented changes
- After merge, the worktree and feature branch are deleted
- Main branch is updated with the merged changes

---

## Phase 1: CI Hard Gate (MANDATORY — run FIRST before any other check)

> ⛔ This is a hard gate. If CI has not passed you MUST NOT proceed to merge.
> The full per-task structured result is evaluated — not just overall pipeline status.

### Step 1.1 — Detect the PR validation job

```bash
# Find the PR validation job for this pipeline
pr_job=$(fly -t ${CI_TARGET} jobs -p "$repo" --json 2>/dev/null \
  | jq -r '[.[].name | select(test("^pr[-_]"; "i") or test("^validate[-_]?pr"; "i") or test("^check[-_]?pr"; "i"))] | first // empty')

# Fallback: scan recent builds for any pr-* job name
if [ -z "$pr_job" ]; then
  pr_job=$(cd $PROJECT_ROOT && npx tsx ~/.claude/skills/ci/list_builds.ts "{\"pipeline\": \"$repo\", \"count\": 10}" \
    | jq -r '[.builds[] | select(.job_name | test("^pr[-_]"; "i"))] | first | .job_name // empty')
fi

# Last resort default
[ -z "$pr_job" ] && pr_job="pr-check"
echo "PR job: $pr_job"
```

### Step 1.2 — Run wait-for-ci and evaluate

```bash
ci_result=$(cd $PROJECT_ROOT && npx tsx ~/.claude/skills/ci/wait_for_ci.ts \
  "{\"repo\": \"$repo\", \"job\": \"$pr_job\", \"timeout_seconds\": 900}")

ci_success=$(echo "$ci_result" | jq -r '.success')
ci_status=$(echo "$ci_result"  | jq -r '.status')
ci_run=$(echo "$ci_result"     | jq -r '.run')
```

Print: `[CI] $ci_status — $ci_run`

### Step 1.3 — Hard gate: block on failure

**If `ci_success` is `false`:**

1. Print the failing tasks and their last log lines:
   ```bash
   echo "$ci_result" | jq -r '.output | to_entries[] | select(.value.success == false) | "  FAILED: \(.key)\n\(.value.logs[-5:] | join("\n"))"'
   ```

2. Reset step label from `step:merging` to `step:fixing-pr`:
   ```bash
   current=$(cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "labels"}')
   labels=$(echo "$current" | jq -r '.fields.labels // [] | map(select(startswith("step:") | not)) + ["step:fixing-pr"] | @json')
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/update_issue.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"labels\": $labels, \"notify_users\": false}"
   ```

3. Execute `/fix-pr $ARGUMENTS.issue` — address the CI failures.

4. Execute `/review $ARGUMENTS.issue` — re-review after the fix is pushed.

5. **STOP. Return `MERGE_BLOCKED: CI failed — $ci_run` to the orchestrator.**
   Do NOT proceed to Phase 2.

**Only continue to Phase 2 if `ci_success` is `true`.**

---

## Gate Check (MANDATORY before merge)

Verify ALL conditions before proceeding:

```
✓ Code review verdict is APPROVED (not REQUIRES REWORK)
✓ CI pipeline status = PASSED (check via Concourse fly skills above, NOT Bitbucket)
✓ All 🔴 Critical comments addressed
✓ All 🟠 Warning comments addressed or justified
✓ All ❓ Questions answered
✓ All 🟡 Suggestions acknowledged
✓ All 🟢 Nitpicks acknowledged
```

### Review Verdict Blocker Check (MANDATORY — run FIRST)

Before checking anything else, verify the most recent code review verdict is not REQUIRES REWORK.
This prevents merging PRs that have unresolved review issues.

```bash
# Fetch Jira comments and find the most recent review verdict
issue=$(npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "comment"}')
# Scan comments in reverse for "### Verdict:" or "**Code Review:"
# The review skill writes verdicts in these formats
```

**If the most recent review verdict is `REQUIRES REWORK`:**
- **STOP immediately.** Do NOT proceed with merge.
- Print: `BLOCKED: Most recent code review verdict is REQUIRES REWORK. Run /fix-pr first.`
- Return to orchestrator with `MERGE_BLOCKED` status.

**If verdict is `APPROVED` or `LGTM`:** proceed with remaining gate checks.

**If no review comment found:** proceed with a warning (the `/work` orchestrator runs `/review`
before `/resolve-pr`, so a missing review is unusual but not blocking).

### How to verify review comments are "addressed"

Bitbucket does NOT auto-resolve inline comments when code is fixed. The presence of warning/critical
comments does NOT mean they are unresolved. You MUST diff-verify:

1. **List PR comments** and note the `created_on` timestamp of each warning/critical comment.
2. **List PR commits** — check if any commits were pushed AFTER the review comments.
3. **If post-review commits exist**, fetch the latest diff and check whether the specific code
   referenced in each comment has changed. For example, if a comment says "line 144: `[class*="error"]`
   is too broad", check whether line 144 still contains that selector.
4. **A comment is addressed if** the code it references has been modified in a post-review commit.
   It does NOT need a reply or "resolved" status — the diff is the source of truth.

```bash
# Get PR comments with timestamps
comments=$(npx tsx ~/.claude/skills/vcs/list_pull_request_comments.ts '{"repo": "<repo>", "pr_number": <num>}')

# Get the latest review comment timestamp
last_review=$(echo "$comments" | jq -r '[.values[] | select(.inline) | .created_on] | sort | last')

# Get PR commits to check if any are newer than the review
pr=$(npx tsx ~/.claude/skills/vcs/get_pull_request.ts '{"repo": "<repo>", "pr_number": <num>}')
head_commit_date=$(echo "$pr" | jq -r '.source.commit.date // empty')

# If head commit is newer than last review comment, fixes were likely pushed
# Then diff-verify: fetch current diff and check each comment's referenced code
diff=$(npx tsx ~/.claude/skills/vcs/get_pull_request_diff.ts '{"repo": "<repo>", "pr_number": <num>}')
# Check whether the specific lines/patterns mentioned in each comment still exist
```

**Only block the merge if** a warning/critical comment references code that is STILL present unchanged
in the latest diff. Do NOT block just because comment objects exist on the PR.

**If ANY condition is genuinely not met:** STOP and tell the user to run `/fix-pr $ARGUMENTS.issue` first.

---

## Finding the Repo and PR Number (MANDATORY — do this FIRST)

Your prompt may include a `PR CONTEXT (pre-fetched)` block with repo, PR number, and merge command.
**If it does:** Use those values directly. Do NOT search for them.

**If it does NOT:** Resolve them with this exact sequence:

```bash
# 1. Try checkpoint (check both orchestrator and agent phases)
checkpoint=$(python3 ~/.claude/hooks/checkpoint.py load "$ARGUMENTS.issue" 2>/dev/null)
repo=$(echo "$checkpoint" | jq -r '.checkpoint.data.repo // empty')
pr_number=$(echo "$checkpoint" | jq -r '.checkpoint.data.pr_number // empty')

# If latest phase lacks repo/pr, try the orch.phase2-complete phase explicitly
if [ -z "$pr_number" ] || [ -z "$repo" ]; then
  orch_cp=$(python3 ~/.claude/hooks/checkpoint.py load "$ARGUMENTS.issue" orch.phase2-complete 2>/dev/null)
  [ -z "$repo" ] && repo=$(echo "$orch_cp" | jq -r '.checkpoint.data.repo // empty')
  [ -z "$pr_number" ] && pr_number=$(echo "$orch_cp" | jq -r '.checkpoint.data.pr_number // empty')
fi

# 2. If still missing, scan for an open PR whose branch contains the issue key
if [ -z "$pr_number" ] && [ -n "$repo" ]; then
  pr_number=$(npx tsx ~/.claude/skills/vcs/list_pull_requests.ts "{\"repo\": \"$repo\", \"state\": \"open\"}" \
    | jq -r ".values[] | select(.source.branch.name | ascii_downcase | contains(\"$(echo $ARGUMENTS.issue | tr A-Z a-z)\")) | .id" | head -1)
fi

# 3. If repo is also missing, check Jira labels for repo-* label
if [ -z "$repo" ]; then
  repo=$(npx tsx ~/.claude/skills/issues/get_issue.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"fields\": \"labels\"}" \
    | jq -r '.fields.labels[] | select(startswith("repo-")) | sub("^repo-"; "")' | head -1)
fi
```

**STOP if repo or pr_number is empty** — print what you found and ask the orchestrator for help.

---

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

1. Resolve repo and PR number (see above)
1b. **CI Hard Gate** — run `wait-for-ci`; if failed → `/fix-pr` → `/review` → STOP (see Phase 1 above)
2. Check review verdict is APPROVED (see Review Verdict Blocker Check) — STOP if REQUIRES REWORK
3. Diff-verify PR review comments (see Gate Check above) - BLOCKER only if issues still present in latest diff
3b. **Pre-Merge Conflict Check** — merge latest main into branch if behind
3c. **Wave-Aware Rebuild Gate** — run repo's validation-commands after merging main to catch semantic collisions
4. Merge PR via VCS API (use `merge_pull_request.ts` — see HARD GUARDRAIL below)
4b. Post merge confirmation comment to clear stale review state (see Post-Merge Review Clearance below)
5. Verify validation criteria stored
6. Transition issue to VALIDATION status (use `list_transitions.ts` then `transition_issue.ts`)
6. Store episode and capture cost
7. Cleanup worktree (LAST — see safety rules below)

### Pre-Merge Conflict Check (MANDATORY — run before merge API call)

Before attempting the Bitbucket merge, verify the branch is up-to-date with main:

```bash
cd <worktree-path>
git fetch origin main

behind=$(git rev-list --count HEAD..origin/main)
if [ "$behind" -gt 0 ]; then
  echo "[branch-sync] Branch is $behind commit(s) behind main — merging"
  git merge origin/main --no-edit
  if [ $? -ne 0 ]; then
    echo "[branch-sync] CONFLICT — resolve conflicts, commit, push, wait for CI, then retry /resolve-pr"
    exit 1
  fi
  git push
  echo "[branch-sync] Merged $behind commit(s) from main and pushed — wait for CI before calling merge API"
  # STOP: re-run /resolve-pr after CI passes on the updated branch
  exit 0
else
  echo "[branch-sync] Branch is up to date with main"
fi
```

**Why this matters:** If another PR lands on main while your PR is in review/fix cycles,
the Bitbucket merge API will reject with "resolve all merge conflicts." Proactively merging
main into the feature branch avoids this surprise at merge time.

### Wave-Aware Rebuild Gate (MANDATORY — run after conflict check, before merge API)

After merging latest main (or confirming the branch is up-to-date), run the repo's
validation-commands to catch **semantic collisions** that text-based merges cannot detect.

**Why this exists:** PROJ-2952 and PROJ-2955 both independently declared `AssignConsultantRequest`
in different files. Bitbucket merged both without conflict (different files), but `go build`
failed on main. For repos with `deploy-strategy: none` there is no post-merge CI to catch this —
the build break wasn't discovered until `/validate` ran. This gate catches it before merge.

```bash
# 1. Read the repo's validation-commands from CLAUDE.md
val_cmds=$(grep -A 10 "^validation-commands:" $PROJECT_ROOT/<repo>/CLAUDE.md 2>/dev/null \
  | grep '^\s*-\s*"' | sed 's/^\s*-\s*"\(.*\)"/\1/')

# 2. If no validation-commands found, try common language-specific builds
if [ -z "$val_cmds" ]; then
  if [ -f "$PROJECT_ROOT/<repo>/go.mod" ]; then
    val_cmds="go build ./..."
  elif [ -f "$PROJECT_ROOT/<repo>/package.json" ]; then
    val_cmds="npm run build"
  elif [ -f "$PROJECT_ROOT/<repo>/Makefile" ]; then
    val_cmds="make build"
  fi
fi

# 3. Run each validation command from the worktree (which now has latest main merged)
if [ -n "$val_cmds" ]; then
  echo "[rebuild-gate] Running validation-commands after merging latest main..."
  cd <worktree-path>
  rebuild_failed=false
  while IFS= read -r cmd; do
    echo "[rebuild-gate] Running: $cmd"
    if ! eval "$cmd" 2>&1; then
      echo "[rebuild-gate] FAILED: $cmd"
      rebuild_failed=true
      break
    fi
  done <<< "$val_cmds"

  if [ "$rebuild_failed" = "true" ]; then
    echo "[rebuild-gate] BLOCKED: Build fails after merging latest main."
    echo "[rebuild-gate] This likely means another recently-merged PR introduced a semantic conflict."
    echo "[rebuild-gate] Fix the collision in the worktree, commit, push, and re-run /resolve-pr."
    # Reset step label to step:fixing-pr
    exit 1
  fi
  echo "[rebuild-gate] All validation-commands passed after merging main."
else
  echo "[rebuild-gate] No validation-commands found — skipping rebuild gate."
fi
```

**When this gate fails:**
1. Print the build error output (it identifies the collision)
2. Reset step label from `step:merging` to `step:fixing-pr`
3. **STOP. Return `MERGE_BLOCKED: Build fails after merging latest main` to the orchestrator.**
4. The developer fixes the collision in the worktree, pushes, and re-runs `/resolve-pr`.

**Performance note:** This adds seconds (Go build) to minutes (npm build) to the merge flow.
For repos with Concourse post-merge CI, the gate is still valuable — it catches failures
*before* merge rather than after, avoiding broken-main windows.

### Post-Merge Review Clearance (MANDATORY — run after successful merge)

After the Bitbucket merge API returns success, post a Jira comment to clear stale review state.
This prevents `/validate` from seeing an old REQUIRES REWORK verdict and short-circuiting.

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.issue", "body": "### Verdict: APPROVED\n\nPR merged to main. Prior review issues resolved."}'
```

**Why this matters:** `/validate` Phase 0.75 scans for the most recent `### Verdict:` comment.
If the last verdict is REQUIRES REWORK (from a prior review cycle), validation skips entirely
and sets `outcome:validation-skipped`. This clearance comment ensures the post-merge verdict
is APPROVED, allowing validation to proceed normally.

---

### Phase 5.5: Post-Merge Local Sync (MANDATORY)

After PR is merged via VCS API:

```bash
cd $PROJECT_ROOT/<repo>
git checkout main
git pull origin main
MERGE_SHA=$(git log --oneline -1 | cut -d' ' -f1)
echo "Local main synced. Latest commit: $MERGE_SHA"
```

If `git pull` fails: warn but do not block (the merge already succeeded via API).

---


### HARD GUARDRAIL: Merge Method

**ONLY use the VCS API to merge PRs:**
```bash
npx tsx ~/.claude/skills/vcs/merge_pull_request.ts '{"repo": "<repo>", "pr_number": <num>}'
```

**NEVER fall back to local git merge + git push to main.** This is PROHIBITED because:
- It bypasses PR merge semantics (no merge commit linked to the PR)
- It can push directly to main, bypassing branch protection
- It has caused shell crashes when combined with worktree cleanup

**If the VCS merge API fails AFTER the pre-merge conflict check:** STOP and report
the error. Do NOT attempt alternative merge strategies. The orchestrator will handle it.

> **Phase ordering rationale:** Worktree cleanup MUST be the LAST phase.
> If cleanup crashes the shell (e.g. removing the cwd), all prior phases
> have already completed. Never reorder cleanup before Jira transitions.

### Worktree Cleanup Safety Rules (Phase 7)

The worktree removal MUST follow these rules to avoid crashing the shell:

```bash
# 1. FIRST: cd to the main repo BEFORE removing the worktree
cd $PROJECT_ROOT/<repo-name>

# 2. THEN: remove the worktree from the main repo directory
git worktree remove $PROJECT_ROOT/worktrees/<worktree-dir> --force

# 3. THEN: delete the remote feature branch
git push origin --delete <branch-name> 2>/dev/null || true
```

**NEVER run `git worktree remove` while your cwd is inside the worktree.**
This deletes the directory out from under the shell, breaking all subsequent commands.

---

## Phase 7: Store Episode and Capture Cost (MANDATORY)

### 7.1 Calculate Reward

Determine the reward based on outcome:
- Success on first attempt (no /fix-pr needed): **1.0**
- Success after retries (1+ /fix-pr rounds): **0.8 - (0.05 * retries)**, minimum 0.5
- Partial success (PR created but issues remain): **0.5**

### 7.2 Store Episode

```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts "{\"session_id\": \"${TENANT_NAMESPACE}\", \"task\": \"/work $ARGUMENTS.issue\", \"input\": {\"issueType\": \"${issueType}\", \"repo\": \"${repo}\"}, \"output\": \"PR merged\", \"reward\": ${reward}, \"success\": true, \"critique\": \"${critique}\"}"
```

### 7.3 Store Success Pattern (if reward >= 0.9)

```bash
# Only store success patterns for high-reward outcomes
npx tsx ~/.claude/skills/agentdb/pattern_store.ts "{\"task_type\": \"${issueType}-work\", \"approach\": \"${approach_summary}\", \"success_rate\": ${reward}}"
```

### 7.4 Capture Session Cost

```bash
python3 ${PROJECT_ROOT}/agents/scripts/capture_session_cost.py "$ARGUMENTS.issue" "work" --json
```

Store cost in AgentDB:

```bash
cost_data=$(python3 ${PROJECT_ROOT}/agents/scripts/capture_session_cost.py "$ARGUMENTS.issue" "work" --json)
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts "{\"session_id\": \"${TENANT_NAMESPACE}-costs\", \"task\": \"cost-$ARGUMENTS.issue-work\", \"input\": $(echo "$cost_data" | jq -c '.'), \"output\": \"\", \"reward\": 1.0, \"success\": true, \"critique\": \"Cost tracking\"}"
```

**START NOW: Begin Phase 0/Step 0.**

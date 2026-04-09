<!-- MODEL_TIER: opus -->
<!-- DISPATCH: Spawn a Task subagent with model: "opus" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Opus. -->

---
description: Work a single Jira issue through to completion with pipeline-aware pausing
arguments:
  - name: issue
    description: Jira issue key (e.g., PROJ-123)
    required: true
  - name: resume
    description: Resume from a paused state (optional)
    required: false
---

# Loop Issue: $ARGUMENTS.issue

## Purpose

This command works a single issue through its entire lifecycle to completion, with intelligent pipeline-aware pausing. When a pipeline is running or needs waiting, it labels and comments on the issue so the loop can resume later.

**Key Feature:** When hitting a "wait for pipeline" step, this command:
1. Labels the issue with `loop-waiting-pipeline`
2. Comments with the current phase and context
3. Exits cleanly so the loop can process other work
4. Can be resumed later with `--resume`

---

## State Machine

This command implements a resumable state machine for a single issue:

```
BACKLOG → IN_PROGRESS (via /work)
IN_PROGRESS → AWAITING_CI (PR created, CI running)
AWAITING_CI → AWAITING_REVIEW (CI green, /review complete)
AWAITING_REVIEW → MERGED (via /resolve-pr)
MERGED → AWAITING_DEPLOY (PR merged, pipeline running)
AWAITING_DEPLOY → VALIDATING (deploy confirmed)
VALIDATING → DONE (via /validate)
```

When in a "WAITING" state: label the issue, comment with context, exit cleanly.
When resumed: load saved state from Jira comment, skip completed phases.

---

## Skill Reference (MANDATORY)

**Always run from `$PROJECT_ROOT`.**

```bash
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "<KEY>", "fields": "summary,status,labels,comment,assignee"}'
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "<KEY>", "labels": [...]}'
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "<KEY>", "body": "<markdown>"}'
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/bitbucket/list_pull_requests.ts '{"repo_slug": "<REPO>", "state": "OPEN"}'
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "<issue> loop state", "top_k": 3}'
```

---

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/5] Executing work...`).

---

### Phase 0: Load Context and Check Resume State

**[phase 0/5] Loading context...**

1. Fetch the issue:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "summary,status,labels,comment,assignee,parent"}'
   ```

2. Check for a resume state comment (look for `<!-- loop-issue-state:` marker):
   ```bash
   # Look in Jira comments for: <!-- loop-issue-state: {"phase": "...", "context": {...}} -->
   ```

3. Check AgentDB for prior state:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "$ARGUMENTS.issue loop issue state", "top_k": 3}'
   ```

4. Determine:
   - `CURRENT_STATUS` — Jira status (Backlog, To Do, In Progress, Validation, Done)
   - `CURRENT_LABELS` — all labels on the issue
   - `RESUME_STATE` — saved phase from prior run (if any)
   - `HAS_OPEN_PR` — check Bitbucket for open PRs for this issue branch

---

### Phase 1: Determine Current State and Next Action

**[phase 1/5] Determining state...**

Map Jira status + labels to the next action:

| Status | Labels present | Action |
|---|---|---|
| Backlog / To Do | none | → dispatch `/work $ARGUMENTS.issue` |
| In Progress | `step:implementing` | → dispatch `/work $ARGUMENTS.issue` (resume) |
| In Progress | `step:awaiting-ci` | → check CI status → if green, dispatch `/review $ARGUMENTS.issue` |
| In Progress | `step:ready-for-review` | → dispatch `/review $ARGUMENTS.issue` |
| In Progress | `step:review-approved`, `step:awaiting-ci` | → dispatch `/resolve-pr $ARGUMENTS.issue` |
| In Progress | `loop-waiting-pipeline` | → check pipeline → if complete, remove label and continue |
| Validation | none | → dispatch `/validate $ARGUMENTS.issue` |
| Done | none | → EXIT: issue already complete |
| Any | `needs-human` | → EXIT: issue blocked, requires human intervention |

If `HAS_OPEN_PR` and status is In Progress with no step label:
- Check the PR state (open, merged, declined)
- Set the appropriate step label then re-evaluate

---

### Phase 2: Execute Appropriate Command

**[phase 2/5] Executing...**

Dispatch the command determined in Phase 1.

#### /work dispatch
```bash
eval $(python3 ~/.claude/hooks/resolve-model.py work --env)
# Dispatch /work $ARGUMENTS.issue via dispatch-local.sh or inline
```

The `/work` command handles the full implementation → PR creation → review → merge lifecycle.
After `/work` completes, re-fetch the issue status and proceed to Phase 3.

#### /validate dispatch
```bash
eval $(python3 ~/.claude/hooks/resolve-model.py validate --env)
# Dispatch /validate $ARGUMENTS.issue
```

The `/validate` command handles post-deploy verification.
After `/validate` completes, re-fetch status and proceed to Phase 4.

#### CI wait handling
If `step:awaiting-ci` label is present:
1. Check Bitbucket pipeline status:
   ```bash
   # Get the branch name from the PR
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/bitbucket/list_pull_requests.ts '{"repo_slug": "<REPO>", "state": "OPEN"}'
   # Get the pipeline for that branch
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/bitbucket/list_pipelines.ts '{"repo_slug": "<REPO>", "branch": "<BRANCH>"}'
   ```
2. If pipeline is still running → go to Phase 3 (pipeline wait)
3. If pipeline passed → dispatch `/review $ARGUMENTS.issue` inline
4. If pipeline failed → dispatch `/fix-pr $ARGUMENTS.issue`

---

### Phase 3: Handle Pipeline Waits with State Persistence

**[phase 3/5] Pipeline wait handling...**

When a pipeline is still running and we cannot proceed:

1. Determine estimated wait (log last build duration if available)

2. Label the issue for resumption:
   ```bash
   # Read current labels, add loop-waiting-pipeline
   CURRENT_LABELS=$(cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "labels"}' | python3 -c "import json,sys; d=json.load(sys.stdin); lbls=d.get('labels',[]); lbls.append('loop-waiting-pipeline') if 'loop-waiting-pipeline' not in lbls else None; print(json.dumps(lbls))")
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/update_issue.ts "{"issue_key": "$ARGUMENTS.issue", "labels": $CURRENT_LABELS}"
   ```

3. Post a resumption comment with current state:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/add_comment.ts '{
     "issue_key": "$ARGUMENTS.issue",
     "body": "## Loop Issue — Waiting for Pipeline

<!-- loop-issue-state: {"phase": "awaiting-ci", "context": {"pr_id": N, "repo": "<REPO>"}} -->

Pipeline is running. Resume with `/loop:issue $ARGUMENTS.issue --resume` once CI completes."
   }'
   ```

4. **EXIT CLEANLY** — do not block waiting. The loop will resume this issue on the next invocation.

---

### Phase 4: Continue or Confirm Completion

**[phase 4/5] Confirming completion...**

After the dispatched command completes:

1. Re-fetch the issue to get updated status and labels
2. Check the updated state:
   - If status = Done → proceed to summary (success)
   - If status = Validation → dispatch `/validate $ARGUMENTS.issue` if not already done
   - If status = In Progress and has actionable step label → loop back to Phase 1
   - If status = In Progress with `needs-human` → exit with blocked status
   - If `loop-waiting-pipeline` label still present → exit cleanly (pipeline still running)

3. Remove `loop-waiting-pipeline` label if pipeline is now complete and we proceeded:
   ```bash
   CURRENT_LABELS=$(cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "labels"}' | python3 -c "import json,sys; d=json.load(sys.stdin); lbls=[l for l in d.get('labels',[]) if l != 'loop-waiting-pipeline']; print(json.dumps(lbls))")
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/update_issue.ts "{"issue_key": "$ARGUMENTS.issue", "labels": $CURRENT_LABELS}"
   ```

4. Store episode in AgentDB:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{
     "session_id": "${TENANT_NAMESPACE}", "task": "loop-issue-$ARGUMENTS.issue",
     "output": "{done|paused|blocked}", "reward": {1.0|0.5|0.0},
     "success": {true|false},
     "critique": "Issue {completed|paused awaiting CI|blocked by needs-human}"
   }'
   ```

---

### Phase 5: Summary

**[phase 5/5] Summary**

```
## Loop Issue: $ARGUMENTS.issue

### Status: DONE | PAUSED | BLOCKED
### Final Jira Status: {status}
### Action Taken: {work|validate|ci-wait|review}
### Next Step: {none (done) | resume with /loop:issue --resume | human intervention required}
```

**START NOW: Begin Phase 0.**

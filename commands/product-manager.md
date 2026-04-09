<!-- MODEL_TIER: opus -->
<!-- DISPATCH: Spawn a Task subagent with model: "opus" to execute this command. -->

---
description: Drive all epics in a roadmap cycle to completion using dependency-aware waves
arguments:
  - name: cycle
    description: Roadmap cycle key (e.g., cycle-0, cycle-1, cycle-ph)
    required: true
---

# Product Manager: $ARGUMENTS.cycle

## MANDATORY: Create Phase TodoWrite Items

Before doing anything else, create these tracking items:

```
TodoWrite({
  todos: [
    { content: "Phase 0: Load and reconcile state vs Jira", status: "pending" },
    { content: "Phase 1: Build dependency wave plan", status: "pending" },
    { content: "Phase 2: Execute waves (spawn epic managers)", status: "pending" },
    { content: "Phase 3: Cycle completion and retrospective", status: "pending" }
  ]
})
```

---

## Overview

Drives all epics in a roadmap cycle to completion. Builds dependency-aware waves from
`roadmap.json`, spawns Epic Manager subagents in parallel per wave, runs cross-epic
impact analysis after each wave, synthesizes a cycle retrospective, and keeps
`roadmap.json` current throughout.

State is checkpointed to:
`$TENANT_DOCS_PATH/operations/agent-state/$ARGUMENTS.cycle/{git-user-email}/product-manager.json`

On re-invocation: reads existing state and resumes from last incomplete phase.
**Jira is always authoritative** — state files are resume hints only.

---

## Phase 0: Load & Reconcile

Mark Phase 0 TodoWrite item as in_progress.

### 0.1 Retrieve patterns from AgentDB

```bash
npx tsx ~/.claude/skills/agentdb/pattern_search.ts '{"task": "product manager cycle epic wave orchestration checkpoint", "k": 5, "threshold": 0.5}'
npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts '{"task": "product-manager $ARGUMENTS.cycle", "k": 3, "threshold": 0.5}'
```

### 0.2 Determine user identity and state paths

```bash
GIT_USER_EMAIL=$(git config user.email)
STATE_DIR="$TENANT_DOCS_PATH/operations/agent-state/$ARGUMENTS.cycle/${GIT_USER_EMAIL}"
STATE_FILE="${STATE_DIR}/product-manager.json"
mkdir -p "$STATE_DIR"
```

Create `_index.yaml` for the cycle directory if it does not already exist:

```bash
CYCLE_INDEX="$TENANT_DOCS_PATH/operations/agent-state/$ARGUMENTS.cycle/_index.yaml"
if [ ! -f "$CYCLE_INDEX" ]; then
cat > "$CYCLE_INDEX" << EOF
directory: $ARGUMENTS.cycle
description: "Agent state for $ARGUMENTS.cycle — one subdirectory per developer email"
contents: []
EOF
fi
```

### 0.3 Load own state file

If `$STATE_FILE` exists:
- Print: `Resuming product-manager $ARGUMENTS.cycle from checkpoint`
- Parse the JSON. Note `currentWave`, `completedEpics`, `failedEpics`, `waves`.

If `$STATE_FILE` does not exist:
- Print: `Starting fresh: product-manager $ARGUMENTS.cycle`
- Initialize:
```json
{
  "cycle": "$ARGUMENTS.cycle",
  "startedAt": "<ISO timestamp>",
  "waves": [],
  "completedEpics": [],
  "failedEpics": [],
  "crossEpicIssuesCreated": [],
  "currentWave": 1
}
```

### 0.4 Read peer state files

```bash
ls "$TENANT_DOCS_PATH/operations/agent-state/$ARGUMENTS.cycle/" 2>/dev/null
```

For each peer directory (email ≠ current user email), read their `product-manager.json` and note their `completedEpics`.

### 0.5 Reconcile against Jira (batched)

Load all epic IDs for this cycle from roadmap.json:

```bash
python3 -c "
import json, os
r = json.load(open(os.path.expandvars('\$TENANT_DOCS_PATH') + '/initiatives/roadmap.json'))
ids = [e['id'] for e in r['epics'] if e['cycleKey'] == '$ARGUMENTS.cycle']
print(','.join(ids))
"
```

Query all epics in a single Jira call:

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "key IN ($EPIC_ID_LIST)", "fields": ["key", "status", "summary"]}'
```

**Jira is truth:**
- For each epic where Jira status = Done → add to `completedEpics` in state and update `roadmap.json` (see 0.6)
- If two peers AND current state both show same epic as `in_progress` AND Jira confirms In Progress → post warning comment:

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "{epicKey}", "body": "⚠️ Conflict: both {currentUser} and {peerUser} have this epic marked as current. Please coordinate."}'
```

### 0.6 Update roadmap.json for Jira-confirmed Done epics

```bash
python3 << 'PYEOF'
import json, os
path = os.path.expandvars('$TENANT_DOCS_PATH') + '/initiatives/roadmap.json'
roadmap = json.load(open(path))
done_epics = SET_OF_DONE_EPIC_IDS_FROM_JIRA  # replace with actual set
for epic in roadmap['epics']:
    if epic['id'] in done_epics:
        epic['status'] = 'Done'
with open(path, 'w') as f:
    json.dump(roadmap, f, indent=2)
print('roadmap.json updated')
PYEOF
```

### 0.7 Commit reconciled state

```bash
cd $TENANT_DOCS_PATH && git pull --rebase && git add operations/agent-state/ initiatives/roadmap.json && git commit -m "chore: product-manager $ARGUMENTS.cycle phase-0 reconcile [$(git config user.email)]" && git push
```

Mark Phase 0 TodoWrite item as completed.

---

## Phase 1: Build Dependency Waves

Mark Phase 1 TodoWrite item as in_progress.

### **GUARD: Skip if `waves` is already populated and non-empty in state**

If state has `waves` with at least one entry and `currentWave` > 0, print:
`Resuming at wave {currentWave} — wave plan already built` and skip to Phase 2.

### 1.1 Build topological sort

```bash
python3 << 'PYEOF'
import json, os

path = os.path.expandvars('$TENANT_DOCS_PATH') + '/initiatives/roadmap.json'
roadmap = json.load(open(path))
cycle_epics = [e for e in roadmap['epics'] if e['cycleKey'] == '$ARGUMENTS.cycle']
completed = set(STATE_COMPLETED_EPICS)  # replace with actual set from state

# Filter to incomplete epics only
remaining = [e for e in cycle_epics if e['id'] not in completed and e.get('status') != 'Done']

if not remaining:
    print('EMPTY_WAVES')
else:
    in_cycle_ids = {e['id'] for e in remaining}
    deps_map = {e['id']: [d for d in e.get('deps', []) if d in in_cycle_ids] for e in remaining}

    waves = []
    resolved = set(completed)
    unresolved = list(remaining)

    while unresolved:
        wave = [e for e in unresolved if all(d in resolved for d in deps_map[e['id']])]
        if not wave:
            print('ERROR: Circular dependency detected')
            break
        waves.append([e['id'] for e in wave])
        resolved.update(e['id'] for e in wave)
        unresolved = [e for e in unresolved if e['id'] not in resolved]

    print(json.dumps(waves))
PYEOF
```

### 1.2 Handle empty waves

If the output is `EMPTY_WAVES`:
- Print: `All epics in $ARGUMENTS.cycle are already Done in Jira. Nothing to do.`
- Skip directly to Phase 3 (Cycle Completion).

### 1.3 Save wave plan and commit

Update state: `{"waves": [{waveNum: 1, epics: [...], status: "pending"}, ...], "currentWave": 1}`

Print the plan:
```
Wave 1 (N epics, no deps): PROJ-XXXX, PROJ-YYYY, ...
Wave 2 (N epics): PROJ-ZZZZ, ...
```

```bash
cd $TENANT_DOCS_PATH && git pull --rebase && git add operations/agent-state/ && git commit -m "chore: product-manager $ARGUMENTS.cycle wave-plan committed [$(git config user.email)]" && git push
```

Mark Phase 1 TodoWrite item as completed.

---

## Phase 2: Execute Waves

Mark Phase 2 TodoWrite item as in_progress.

Loop until all waves have `status: complete`:

### 2.0.5 Skeleton Gate (before each wave)

Before spawning Epic Manager Tasks for the current wave, verify each epic has a validated walking skeleton.

For each epic in the current wave that is NOT already in `completedEpics`:

1. Search for skeleton issues:
```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "parent = {epicKey} AND labels = skeleton", "fields": ["key", "summary", "status", "labels"]}'
```

2. **If NO skeleton issues found:**
   - Log: `Epic {epicKey} has no skeleton - creating one before starting work`
   - Invoke `/create-skeleton {epicKey}`
   - Invoke `/review-skeleton {epicKey}`
   - If review verdict is NEEDS_FIXES: invoke `/fix-skeleton {epicKey}`, then re-review (max 2 cycles)
   - If review verdict is REJECTED after 2 fix cycles: log warning, add epic to `failedEpics` with blocker "skeleton rejected", skip this epic in the wave

3. **If skeleton issues exist but NOT all have `outcome:success-validation` label:**
   - Log: `Epic {epicKey} skeleton not yet validated - skeleton issues will be worked first by epic-manager`
   - Proceed (the epic-manager Phase 0.5 will enforce skeleton-first ordering)

4. **If all skeleton issues have `outcome:success-validation`:**
   - Log: `Epic {epicKey} skeleton validated - ready for full implementation`

### 2.1 Spawn Epic Manager Tasks for current wave (parallel)

For each epic in the current wave that is NOT already in `completedEpics`:

Spawn a Task subagent for each epic simultaneously. Use model: opus. For each Task, provide this prompt (substituting the actual epic key):

> You are an Epic Manager agent. Your sole job is to drive epic {epicKey} to Done by following the phases defined in the epic-manager command.
>
> Read the command file at `~/.claude/commands/epic-manager.md` and follow every phase exactly as written, substituting {epicKey} for `$ARGUMENTS.epic` throughout.
>
> You have access to all skills at `~/.claude/skills/`. All skill invocations must be run from `$PROJECT_ROOT` (the directory containing `.env` and `.claude/`).
>
> **MANDATORY: Every child issue MUST be worked through the full workflow command chain:**
> - `/work {ISSUE-KEY}` — claim, plan, implement (TDD), create PR
> - `/review {ISSUE-KEY}` — code review immediately after PR creation
> - `/fix-pr {ISSUE-KEY}` — fix any CI failures or review comments
> - `/resolve-pr {ISSUE-KEY}` — merge only when CI green + review approved
> - `/validate {ISSUE-KEY}` — post-deployment validation with evidence; transitions to Done
>
> **You MUST NOT:**
> - Manually transition a Jira issue to Done without running `/validate`
> - Mark an issue complete without a merged PR in Bitbucket
> - Skip `/review` or `/resolve-pr`
> - Claim issues are done based on planning, grooming, or analysis alone
>
> Each issue is only complete when `/validate` produces evidence and the Jira status is Done via that command's transition. No exceptions.
>
> When all phases are complete, return:
> `{"epicKey": "{epicKey}", "status": "complete", "summary": "brief summary of what was done", "issueCount": N, "prsMerged": N}`
>
> If you cannot complete the epic, return:
> `{"epicKey": "{epicKey}", "status": "failed", "blocker": "description of what blocked you"}`

Wait for ALL Tasks in the wave to return before continuing.

### 2.2 Process wave results

For each Task result:

**If `status: complete`:** → do NOT accept this at face value. Proceed to **Phase 2.2.5 Completion Audit** before marking the epic done.

**If `status: failed`:**
- Add to `failedEpics` with blocker reason
- Post Jira comment on the epic:
```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "{epicKey}", "body": "⚠️ Epic Manager reported failure: {blocker}\n\nManual intervention may be needed."}'
```

---

### 2.2.5 Epic Completion Audit (MANDATORY — runs for every `status: complete` claim)

**Never trust the epic manager's self-report. Verify independently.**

#### Step A: Pull all child issues from Jira

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "\"Epic Link\" = {epicKey} OR parent = {epicKey}", "fields": ["key", "summary", "status", "comment", "issuelinks"]}'
```

Tally:
- `totalIssues` = total count
- `doneIssues` = issues with status = Done
- `notDoneIssues` = everything else (list them)

**If `notDoneIssues` is non-empty:** the epic is NOT complete. Add to `failedEpics` with message listing the open issues. Post a Jira comment:

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "{epicKey}", "body": "🚨 PM Audit FAILED: Epic marked complete by epic manager but {N} issues are not Done: {list}. Returning to in-progress."}'
```

Do NOT proceed to Step B — skip to the failure path.

#### Step B: Verify each Done issue has a merged PR

For each issue in `doneIssues`, check Bitbucket for a merged PR:

```bash
npx tsx ~/.claude/skills/bitbucket/list_pull_requests.ts '{"repo_slug": "{repoSlug}", "state": "MERGED", "query": "{issueKey}"}'
```

Also check if the issue has any linked PRs via Jira:

```bash
npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "{issueKey}", "fields": ["issuelinks", "comment", "status"]}'
```

For each issue, flag it as **SUSPICIOUS** if:
- No linked PR found in Bitbucket or Jira remote links
- The only PR found has state OPEN or DECLINED (not MERGED)
- The issue was transitioned to Done with no PR evidence at all

#### Step C: Verify validation evidence in Jira comments

For each Done issue, scan its Jira comments for validation evidence. Look for at least one comment containing any of:
- The word "validate" or "validation"
- Screenshot references or deployment confirmations
- Test result output or pass/fail evidence
- The phrase "transitions to Done"

Flag as **SUSPICIOUS** if the most recent status transition to Done has no accompanying comment with evidence.

#### Step D: Compute audit score and decide

```
suspiciousCount = number of SUSPICIOUS issues
auditScore = (doneIssues - suspiciousCount) / totalIssues
```

**If `auditScore < 0.80` (more than 20% of issues are suspicious):**
- Add epic to `failedEpics` with audit findings
- Post a detailed Jira comment on the epic:

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{
  "issue_key": "{epicKey}",
  "body": "🚨 PM Completion Audit FAILED\n\nAudit score: {auditScore:.0%} ({doneIssues - suspiciousCount}/{totalIssues} issues verified)\n\nSuspicious issues (closed without evidence):\n{list each with reason}\n\nThese issues must be re-worked through the full /work → /validate workflow before this epic can be marked Done."
}'
```

- Do NOT add to `completedEpics`. Do NOT update `roadmap.json`.
- Consider re-spawning the epic manager with explicit remediation instructions (see 2.2.6).

**If `auditScore >= 0.80`:**
- Log audit results with counts
- Post a brief passing comment on the epic:

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "{epicKey}", "body": "✅ PM Completion Audit PASSED: {doneIssues - suspiciousCount}/{totalIssues} issues verified with merged PRs and validation evidence. Epic approved as complete."}'
```

- Verify Jira epic status is Done (not just child issues):

```bash
npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "{epicKey}", "fields": ["status"]}'
```

- Add to `completedEpics`, update `roadmap.json` status to `"Done"` (use Python from Phase 0.6 pattern)
- Proceed to Cross-Epic Impact Analysis (see 2.3)

---

### 2.2.6 Re-spawn Epic Manager for Audit Failures (if warranted)

If the audit failed with `auditScore < 0.80` AND this is the first failure for this epic (not a repeat):

Spawn a new Task subagent with model: opus and this remediation prompt:

> Epic {epicKey} failed the Product Manager's completion audit. The following issues were closed without evidence of merged PRs or validation:
> {list of suspicious issues with reasons}
>
> Your job is to re-work ONLY these specific issues through the full workflow:
> `/work {issueKey}` → `/review {issueKey}` → `/fix-pr {issueKey}` → `/resolve-pr {issueKey}` → `/validate {issueKey}`
>
> Do NOT re-work issues that already passed audit. Do NOT create new issues.
> Each issue must end with `/validate` producing a Jira comment containing deployment evidence before it can be considered Done.
>
> Return: `{"epicKey": "{epicKey}", "remediatedIssues": [...], "status": "complete" | "failed", "blocker": "..."}`

After the remediation agent returns, re-run the full audit (Steps A–D) one more time.
If the epic still fails after one remediation attempt: add to `failedEpics` permanently and post a `needs-human` Jira comment.

---

Commit updated state and roadmap.json:
```bash
cd $TENANT_DOCS_PATH && git pull --rebase && git add operations/agent-state/ initiatives/roadmap.json && git commit -m "chore: product-manager $ARGUMENTS.cycle wave-{N} results [$(git config user.email)]" && git push
```

### 2.3 Cross-Epic Impact Analysis (after each completed epic)

Spawn a Task subagent with model: opus. Provide this prompt:

> You are a senior architect performing cross-epic impact analysis.
>
> Epic {epicKey} ({epicName}) just completed. Its PRP is at `$TENANT_DOCS_PATH/{prpPath}`.
>
> In-flight epics still being worked in this cycle:
> {list of incomplete epicKey, epicName, pRP path for each}
>
> Review the completed epic's PRP and identify:
> 1. Shared types, API contracts, or interfaces it changed
> 2. Data model changes that affect in-flight epics
> 3. Auth or permission changes with cross-epic impact
>
> For each impact found, create a Jira issue linked to the AFFECTED epic:
> ```
> npx tsx ~/.claude/skills/issues/create_issue.ts '{...}'
> ```
> Then post a comment on the affected epic's Jira issue describing the required action:
> ```
> npx tsx ~/.claude/skills/issues/add_comment.ts '{...}'
> ```
>
> Return JSON only:
> `{"impactsFound": [{"affectedEpic": "PROJ-XXXX", "issueCreated": "PROJ-YYYY", "description": "..."}]}`

Add any created issues to `crossEpicIssuesCreated` in state.

### 2.4 Advance to next wave

Mark current wave `status: complete` in state. Increment `currentWave`. Commit state.

If all waves complete → proceed to Phase 3.

Mark Phase 2 TodoWrite item as completed.

---

## Phase 3: Cycle Completion

Mark Phase 3 TodoWrite item as in_progress.

### 3.1 Final Jira reconciliation

Query all cycle epics (batched JQL, same as Phase 0.5). Any not Done in Jira → add to `failedEpics` with a warning. Log but do not block.

For any epic that is Done in Jira but was NOT audited in Phase 2.2.5 (e.g., it was already Done before this cycle run), run a lightweight spot-check:

```bash
# Count child issues and how many are Done
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "(\"Epic Link\" = {epicKey} OR parent = {epicKey}) AND status != Done", "fields": ["key", "summary", "status"]}'
```

If any child issues are NOT Done on an epic the cycle reports as complete, add a warning comment on the epic and flag it in the retrospective as a data integrity concern. Do not fail the cycle — log only.

### 3.2 Update roadmap.json for all confirmed-Done epics

Use the Python read-modify-write pattern from Phase 0.6.

### 3.3 Collect epic reflections and synthesize cycle retrospective

```bash
find "$TENANT_DOCS_PATH/operations/agent-state/$ARGUMENTS.cycle" -name "epic-*-reflection.md" 2>/dev/null
```

Spawn a Task subagent with model: opus. Provide this prompt:

> You are a senior engineering lead synthesizing a cycle retrospective for $ARGUMENTS.cycle.
>
> Epic reflection documents (one per completed epic):
> {concatenated content of all found epic-*-reflection.md files}
>
> Produce a cycle retrospective in this exact format — include all frontmatter:
>
> ```
> ---
> title: "Cycle $ARGUMENTS.cycle Retrospective"
> status: evergreen
> type: reference
> domain: platform
> ---
>
> # Cycle $ARGUMENTS.cycle Retrospective
>
> ## Cross-Epic Patterns
> [observations that appeared in multiple epics]
>
> ## Systemic Gaps
> [structural problems in process, tooling, or PRP quality]
>
> ## Top Recommendations for Next Cycle
> 1. [concrete, actionable]
> 2. ...
> 3. ...
> 4. ...
> 5. ...
> ```
>
> Return the full markdown text including frontmatter.

Write the returned content to:
`$TENANT_DOCS_PATH/operations/agent-state/$ARGUMENTS.cycle/cycle-retrospective.md`

### 3.4 Commit everything and push

```bash
cd $TENANT_DOCS_PATH && git pull --rebase && git add operations/agent-state/ initiatives/roadmap.json && git commit -m "feat: cycle $ARGUMENTS.cycle complete — retrospective and roadmap.json updated [product-manager]" && git push
```

### 3.5 Slack notification

```bash
npx tsx ~/.claude/skills/slack/send_message.ts '{"text": "✅ Cycle $ARGUMENTS.cycle complete. Epics done: {count}. Retrospective at project-docs/operations/agent-state/$ARGUMENTS.cycle/cycle-retrospective.md", "channel": "$SLACK_DEFAULT_CHANNEL"}'
```

### 3.6 Store completion pattern in AgentDB

```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{"session_id": "${TENANT_NAMESPACE}", "task": "product-manager-$ARGUMENTS.cycle-complete", "reward": 1.0, "success": true, "critique": "Cycle complete. Waves: {waveCount}. Epics done: {doneCount}, failed: {failedCount}."}'
```

Mark Phase 3 TodoWrite item as completed.

---

## Completion Summary

Print on finish:

```
Product Manager: $ARGUMENTS.cycle COMPLETE

Waves executed:             {N}
Epics completed:            {list}
Epics failed:               {list or "none"}
Cross-epic issues created:  {list or "none"}
Retrospective:              project-docs/operations/agent-state/$ARGUMENTS.cycle/cycle-retrospective.md
```

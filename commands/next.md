<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Find and start work on the next priority Jira issue
---

# Find Next Available Issue

## Pre-Flight: VALIDATION Drain and Environment Health

Run these two checks before any other phase. They block or warn before new work is selected.

### Check 1: VALIDATION Queue (BLOCKING)

Issues stuck in VALIDATION must be resolved before starting new work. Issues with
`step:needs-human` are exempt — they are acknowledged as blocked and parked.

```bash
validation_issues=$(npx tsx ~/.claude/skills/issues/search_issues.ts \
  "{\"jql\": \"project = ${TENANT_PROJECT} AND status = VALIDATION AND labels not in (\\\"step:needs-human\\\")\", \"fields\": [\"key\",\"summary\"], \"max_results\": 10}")
count=$(echo "$validation_issues" | jq -r '.total // 0')
if [ "$count" -gt 0 ]; then
  echo "BLOCKED: $count issue(s) in VALIDATION must be resolved before starting new work:"
  echo "$validation_issues" | jq -r '.issues[] | "  - \(.key): \(.fields.summary)"'
  echo ""
  echo "Run: /validate <issue-key>"
  echo "If the issue is blocked by infra and cannot be validated now:"
  echo "  Add label 'step:needs-human' to park it and unblock /next"
  exit 0
fi
```

### Check 2: Environment Smoke Check (NON-BLOCKING)

Run a quick functional smoke check before picking new work. A failure is a signal that
something broke since the last session — not a hard block, but worth knowing before starting.

```bash
if [ -f "$PROJECT_ROOT/$TENANT_SMOKE_TEST_PATH" ]; then
  smoke_output=$(node "$PROJECT_ROOT/$TENANT_SMOKE_TEST_PATH" \
    --env dev --timeout 30 --output /tmp/smoke-next-check.json 2>&1)
  smoke_exit=$?
  if [ $smoke_exit -ne 0 ]; then
    echo "SMOKE_FAIL: Environment health check failed before picking new work."
    echo "$smoke_output" | tail -5
    echo ""
    echo "This may indicate a regression from a recent merge."
    echo "Continuing — investigate with /investigate if needed."
    echo ""
  fi
fi
```

---

## Phase 0: Read Sequence Manifest

Before any Jira queries, read the cached sequence manifest from AgentDB:

```bash
manifest_raw=$(npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "sequence-manifest-latest", "k": 1}' 2>/dev/null || echo '[]')
```

Parse the manifest to extract per-issue sequence data. Store as a lookup map: `{issueKey: {sequencePosition, unblocksCount, consolidateWith}}`.

**Staleness handling:**
- Extract `generatedAt` from the manifest's `approach` JSON field
- If `generatedAt` is within 4 hours: use silently
- If `generatedAt` is older than 4 hours: use data but append notice at end of output: `⚠ Sequence data is X hours old. Run /garden to refresh.`
- If manifest not found or empty: append notice at end: `ℹ No sequence data found. Run /garden to enable sequencing recommendations.`

Store the manifest map in a variable for use in Step 4.

---

## Phase 0.1: Retrieve Relevant Patterns

**Retrieve patterns before finding next issue:**

```bash
# Search for issue selection patterns
npx tsx ~/.claude/skills/agentdb/pattern_search.ts '{"task": "next issue selection patterns", "k": 5, "threshold": 0.6}'

# Retrieve relevant episodes for priority selection
npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts '{"task": "next priority selection", "k": 3}'
```

**Pattern Review:**
- [ ] Reviewed patterns for issue prioritization
- [ ] Noted successful selection strategies
- [ ] Applied lessons from prior selections

---

## Step 0: Load Context

### 0.1 Load Context (TOKEN OPTIMIZATION)

**Check for in-progress work:**
```bash
# Search for work in progress
npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "impl active-workflow", "k": 5}'
```

If prior work exists, remind user before starting new issue.

### 0.2 AgentDB Memory Integration

**Deep memory search for context:**
```bash
# Search for all work-in-progress and completed items
npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "impl merged done", "k": 20}'

# Check for blocked or needs-human issues
npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "needs-human blocked", "k": 10}'
```

---

## Priority Order (UPDATED)

Issues are prioritized in this order:
1. **Needs Attention** - Issues with failure/needs-changes outcome labels (highest priority - unblock stuck issues)
2. **Validation** - Issues awaiting validation (complete deployed work first)
3. **Bugs in To Do** - Fix bugs before starting new features
4. **Other To Do Issues** - Tasks/stories ordered by epic and priority
5. **Within each category**: Epic order → Jira Priority → Age (oldest first)

## Step 0.5: Query for Issues Needing Attention

Search for issues with failure or needs-changes outcomes (highest priority - unblock stuck issues):

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${TENANT_PROJECT} AND labels IN (\"outcome:needs-changes\", \"outcome:failure-validation\", \"outcome:failure-merge-blocked\") AND labels NOT IN (\"outcome:needs-human\", \"blocked\") ORDER BY priority DESC", "fields": ["summary", "status", "priority", "labels", "issuetype", "parent"], "max_results": 3}'
```

**If any issues need attention, prioritize them over validation and other work.**

## Step 1: Query for Issues in Validation

Search for issues needing validation (highest priority - complete deployed work):

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${TENANT_PROJECT} AND status = \"Validate\" AND labels NOT IN (\"needs-human\", \"blocked\") ORDER BY priority DESC, created ASC", "fields": ["summary", "status", "priority", "labels", "issuetype", "parent"], "max_results": 3}'
```

## Step 2: Query for Bugs in To Do

Search for unassigned bug issues (second priority):

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${TENANT_PROJECT} AND issuetype = Bug AND status IN (\"To Do\", \"Open\") AND assignee IS EMPTY AND labels NOT IN (\"needs-human\", \"blocked\") ORDER BY priority DESC, created ASC", "fields": ["summary", "status", "priority", "labels", "issuetype", "parent"], "max_results": 3}'
```

## Step 3: Query for Other To Do Issues by Epic Order

Search for tasks/stories, ordered by parent epic:

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${TENANT_PROJECT} AND issuetype != Bug AND status IN (\"To Do\", \"Open\") AND assignee IS EMPTY AND labels NOT IN (\"needs-human\", \"blocked\") ORDER BY parent ASC, priority DESC, created ASC", "fields": ["summary", "status", "priority", "labels", "issuetype", "parent"], "max_results": 5}'
```


## Step 3.5: Skeleton Dependency Check

For each candidate issue from Steps 1-3, check if its parent epic has skeleton issues:

```bash
# For each candidate with a parent epic, check for skeleton issues
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "parent = {epic_key} AND labels = skeleton", "fields": ["key", "summary", "status", "labels"], "max_results": 20}'
```

**Filtering rules:**

1. If the parent epic has skeleton issues AND any skeleton issue does NOT have
   `outcome:success-validation` label:
   - If this candidate IS a skeleton issue (has `skeleton` label): **eligible** -- prioritize it
   - If this candidate is NOT a skeleton issue: **SKIP** -- skeleton must be validated first

2. If the parent epic has no skeleton issues, or all skeleton issues have
   `outcome:success-validation`: candidate is eligible normally.

3. Collect epic context for the selected issue to pass to `/work`:
   ```json
   {
     "epic_key": "{parent_epic}",
     "epic_goal": "{epic_summary}",
     "epic_unblocks": ["{dependent_epic_keys}"],
     "issue_key": "{selected_issue}",
     "skeleton_status": "validated|pending|missing"
   }
   ```

**Display:** In the Tasks by Epic Priority table, append a `Skel` column showing
`validated`, `pending`, or `--` for the skeleton status of each candidate's parent epic.

---
## Step 4: Present Combined Results

Show issues needing attention first, then validation issues, then bugs, then other issues:

### Needs Attention (Unblock First)
| # | Key | Priority | Type | Summary | Outcome Label |
|---|-----|----------|------|---------|---------------|
| 1 | PROJ-XXX | High | Task | Failed validation or needs changes... | outcome:failure-validation |

### Validation (Complete Second)
| # | Key | Priority | Type | Summary | Parent Epic |
|---|-----|----------|------|---------|-------------|
| 2 | PROJ-XXX | High | Task | Deployed work awaiting validation... | PROJ-YYY |

### Bugs in To Do (Fix Third)
| # | Key | Priority | Summary | Parent Epic |
|---|-----|----------|---------|-------------|
| 3 | PROJ-XXX | High | Bug description... | PROJ-YYY |

### Tasks by Epic Priority
| # | Key | Priority | Type | Summary | Parent Epic | Seq | Unblocks |
|---|-----|----------|------|---------|-------------|-----|----------|
| 4 | PROJ-AAA | High | Task | ... | PROJ-100 (earliest epic) | 1 | 3 |
| 5 | PROJ-BBB | Medium | Task | ... | PROJ-100 | 2 | 1 |
| 6 | PROJ-CCC | High | Task | ... | PROJ-150 (later epic) | — | — |

Populate `Seq` with the `sequencePosition` from the manifest (show `—` if no manifest data), and `Unblocks` with the `unblocksCount` (show `—` if no manifest data).

### Consolidation Opportunities

If any issues in the current list have `consolidateWith` data in the manifest, show:

```
PROJ-234 + PROJ-312 are consolidation candidates — same module, could be one PR.
```

(Only show this section if consolidation candidates exist.)

Ask: "Which issue would you like to work on? (1-N or issue key)"

## Step 5: Start Work

Print any staleness notice captured in Phase 0 before proceeding (e.g., `⚠ Sequence data is X hours old. Run /garden to refresh.` or `ℹ No sequence data found. Run /garden to enable sequencing recommendations.`). If the manifest was fresh and valid, print nothing.

Once user selects an issue:
- For **Needs Attention** issues → execute `/work <selected-issue-key>` (retry with fixes)
- For **Validation** issues → execute `/validate <selected-issue-key>`
- For **To Do** issues → execute `/work <selected-issue-key>`

---

## Performance Tracking (NEW)

**After selection, track the pattern:**
```bash
# Store selection pattern
selection_data=$(cat <<EOF
{
  "selected_type": "bug",
  "priority": "high",
  "epic": "parent-epic-key",
  "selected_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
)

npx tsx ~/.claude/skills/agentdb/pattern_store.ts "{\"task_type\": \"next-issue-selection\", \"approach\": \"priority-based\", \"success_rate\": 1.0, \"metadata\": $(echo "$selection_data" | jq -c .)}"
```

## Alternative: Auto-Pick Highest Priority

If user says "auto" or "just pick one":
1. If any issues need attention → pick the first needs-attention issue (unblock stuck work)
2. If any validation issues exist → pick the first validation issue
3. If any bugs in To Do exist → pick the first bug
4. Otherwise → among tasks from the earliest epic, prefer the one with the highest `unblocksCount` (from sequence manifest). If no manifest data, pick by creation order.

## Epic Dependency Reference

When determining epic order, consider these factors:
- Epic key number (lower = created earlier, typically higher priority)
- Epic's own priority field
- Epic labels (e.g., `mvp`, `critical-path`)

If you need to check epic dependencies, query:
```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${TENANT_PROJECT} AND issuetype = Epic AND status != Done ORDER BY key ASC", "fields": ["summary", "status", "priority", "labels"], "max_results": 10}'
```

---

## Pattern Learning Integration

**Issue selection patterns are stored in AgentDB for future optimization.**

After issue selection, record the pattern:
```bash
# When validation issues are found and selected
npx tsx ~/.claude/skills/agentdb/pattern_store.ts '{"task_type": "next-validation-selection", "approach": "priority-based", "success_rate": 1.0, "metadata": {"issue_key": "<selected-key>", "priority": "<priority>"}}'

# When bugs are found and selected
npx tsx ~/.claude/skills/agentdb/pattern_store.ts '{"task_type": "next-bug-selection", "approach": "priority-based", "success_rate": 1.0, "metadata": {"issue_key": "<selected-key>", "priority": "<priority>"}}'

# When tasks are selected by epic order
npx tsx ~/.claude/skills/agentdb/pattern_store.ts '{"task_type": "next-task-selection", "approach": "epic-order", "success_rate": 1.0, "metadata": {"issue_key": "<selected-key>", "epic": "<parent-epic>", "priority": "<priority>"}}'

# When user selects auto-pick
npx tsx ~/.claude/skills/agentdb/pattern_store.ts '{"task_type": "next-auto-selection", "approach": "auto-pick", "success_rate": 1.0, "metadata": {"issue_key": "<selected-key>", "type": "<validation|bug|task>"}}'
```

**Selection metrics captured:**
- Validation vs bug vs task selection ratio
- Epic priority adherence
- User selection patterns (manual vs auto)

This helps optimize issue prioritization recommendations over time.

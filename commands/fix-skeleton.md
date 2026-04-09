<!-- MODEL_TIER: sonnet -->
<!-- DISPATCH: Spawn a Task subagent with model: "sonnet" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Sonnet. -->

---
description: Fix gaps identified by /review-skeleton and re-submit for review (max 2 cycles)
arguments:
  - name: epic
    description: Jira Epic key (e.g., PROJ-123)
    required: true
---

> Tool examples: [search_issues](.claude/skills/examples/jira/search_issues.md), [create_issue](.claude/skills/examples/jira/create_issue.md), [update_issue](.claude/skills/examples/jira/update_issue.md), [add_comment](.claude/skills/examples/jira/add_comment.md)

# Fix Walking Skeleton: $ARGUMENTS.epic

## Overview

Takes the output of `/review-skeleton` and systematically addresses each identified gap.
Creates missing skeleton issues, adds missing repos, expands E2E coverage, and fixes
dependency links. After fixes, re-submits to `/review-skeleton` for re-validation.

**Max 2 fix-review cycles.** If the skeleton is still not APPROVED after 2 cycles, escalate to user.

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/5] Creating missing issues...`).

1. Phase 0: Load Review Feedback
2. Phase 1: Categorize Gaps
3. Phase 2: Fix Gaps
4. Phase 3: Update Skeleton Document
5. Phase 4: Re-Submit for Review

**START NOW: Begin Phase 0.**

---

## Phase 0: Load Review Feedback

**[phase 0/5] Loading review feedback...**

1. Read the most recent `/review-skeleton` output for this epic.
   Check AgentDB for skeleton review data:
   ```bash
   npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "skeleton-review-$ARGUMENTS.epic", "k": 1}'
   ```

2. If no review feedback found, run the review first:
   ```
   Invoke /review-skeleton $ARGUMENTS.epic
   ```

3. Parse the verdict and gaps list from the review output.

4. Track the current fix cycle:
   ```bash
   npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "skeleton-fix-cycle-$ARGUMENTS.epic", "k": 1}'
   ```
   If this is cycle 3 or higher: STOP. Escalate to user:
   ```
   ESCALATION: Skeleton for $ARGUMENTS.epic failed review after 2 fix cycles.
   Gaps remaining: {list}
   Manual intervention required.
   ```

Store as `REVIEW_VERDICT`, `GAPS[]`, `FIX_CYCLE` (1 or 2).

---

## Phase 1: Categorize Gaps

**[phase 1/5] Categorizing gaps...**

Sort each gap into a fix category:

| Category | Gap Type | Fix Action |
|----------|----------|------------|
| **Missing Repo** | Repository not represented in skeleton | Create new skeleton issue for that repo |
| **Missing E2E** | No E2E test definition | Create e2e-tests skeleton issue or expand existing |
| **Missing Links** | Non-skeleton issues not blocked by skeleton | Add dependency links |
| **Incomplete Scope** | Skeleton issue exists but scope is too narrow | Update issue description with broader scope |
| **Structural** | Files/routes/endpoints not accounted for | Update skeleton issue descriptions |

Print categorized gap summary.

---

## Phase 2: Fix Gaps

**[phase 2/5] Fixing identified gaps...**

### Fix: Missing Repo Issues

For each repo missing a skeleton issue:

```bash
npx tsx ~/.claude/skills/issues/create_issue.ts '{
  "project_key": "${TENANT_PROJECT}",
  "summary": "[Skeleton] ${EPIC_SUMMARY} - {missing_repo}",
  "issue_type": "Task",
  "parent_key": "$ARGUMENTS.epic",
  "labels": ["skeleton", "repo-{missing_repo}"],
  "description": "## Walking Skeleton Task\n\n**Epic:** $ARGUMENTS.epic\n**Repository:** {missing_repo}\n**Skeleton scope:**\n\n{derived minimal scope}\n\n**Acceptance Criteria:**\n- [ ] Minimal implementation compiles and deploys\n- [ ] End-to-end path exercisable\n- [ ] No dead code or orphaned imports"
}'
```

### Fix: Missing E2E Tests

If no E2E skeleton issue exists:

```bash
npx tsx ~/.claude/skills/issues/create_issue.ts '{
  "project_key": "${TENANT_PROJECT}",
  "summary": "[Skeleton] ${EPIC_SUMMARY} - e2e-tests journey tests",
  "issue_type": "Task",
  "parent_key": "$ARGUMENTS.epic",
  "labels": ["skeleton", "repo-e2e-tests", "test-task"],
  "description": "## Walking Skeleton E2E Tests\n\n**Epic:** $ARGUMENTS.epic\n\n**Journey test:** tests/journeys/{domain}.spec.ts\n**Page objects:** pages/{PageName}.ts\n\n**Acceptance Criteria:**\n- [ ] Journey test exercises skeleton end-to-end\n- [ ] Happy path passes"
}'
```

### Fix: Missing Dependency Links

For each non-skeleton issue without proper blocking links:

```bash
npx tsx ~/.claude/skills/issues/update_issue.ts '{
  "issue_key": "{unlinked_child_key}",
  "fields": {
    "issuelinks": [{"type": {"name": "Blocks"}, "inwardIssue": {"key": "{skeleton_key}"}}]
  }
}'
```

### Fix: Incomplete Scope

For skeleton issues that need broader scope, update their descriptions:

```bash
npx tsx ~/.claude/skills/issues/update_issue.ts '{
  "issue_key": "{skeleton_issue_key}",
  "fields": {
    "description": "{updated_description_with_expanded_scope}"
  }
}'
```

Print summary of all fixes applied.

---

## Phase 3: Update Skeleton Document

**[phase 3/5] Updating skeleton document...**

1. Re-read the current skeleton doc:
   ```bash
   cat ${DESIGN_DOCS_PATH}/skeletons/$ARGUMENTS.epic-skeleton.md 2>/dev/null
   ```

2. Update it with the new skeleton issues and expanded scope.

3. Store the fix cycle in AgentDB:
   ```bash
   npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{
     "session_id": "${TENANT_NAMESPACE}",
     "task": "skeleton-fix-cycle-$ARGUMENTS.epic",
     "reward": 0.7,
     "success": true,
     "metadata": {
       "cycle": ${FIX_CYCLE},
       "gaps_fixed": ${GAPS_FIXED_COUNT},
       "gaps_remaining": ${GAPS_REMAINING_COUNT}
     }
   }'
   ```

---

## Phase 4: Re-Submit for Review

**[phase 4/5] Re-submitting for review...**

```
Invoke /review-skeleton $ARGUMENTS.epic
```

### After Re-Review

- If **APPROVED**: Done. Skeleton is ready for implementation.
- If **NEEDS_FIXES** and `FIX_CYCLE < 2`: Increment cycle and loop back to Phase 1.
- If **NEEDS_FIXES** and `FIX_CYCLE >= 2`: Escalate to user:
  ```
  ESCALATION: Skeleton for $ARGUMENTS.epic failed review after 2 fix cycles.
  Remaining gaps: {list}
  Manual intervention required -- review the skeleton document at:
  ${DESIGN_DOCS_PATH}/skeletons/$ARGUMENTS.epic-skeleton.md
  ```
- If **REJECTED**: Escalate immediately (fundamental issues cannot be incrementally fixed):
  ```
  ESCALATION: Skeleton for $ARGUMENTS.epic was REJECTED after fixes.
  Reason: {rejection reason}
  Consider re-running /create-skeleton $ARGUMENTS.epic with revised PRP content.
  ```

---

## Anti-Patterns

| Don't | Do Instead |
|---|---|
| Run more than 2 fix cycles | Escalate to user after 2 cycles |
| Fix gaps without re-reviewing | Always re-submit to /review-skeleton |
| Silently skip unfixable gaps | Document and escalate |
| Create duplicate skeleton issues | Check existing skeleton issues before creating |

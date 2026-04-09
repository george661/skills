<!-- MODEL_TIER: opus -->
<!-- INLINE: This sub-command runs inline within the /validate orchestrator. -->
<!-- This file is reference documentation — it is NOT dispatched via dispatch-local.sh. -->
---
description: Transition Jira issue based on validation verdict
arguments:
  - name: issue
    description: Jira issue key (e.g., PROJ-123)
    required: true
  - name: verdict
    description: "TRANSITION_DONE | TRANSITION_TODO | NEEDS_DEPLOY | NEEDS_HUMAN"
    required: true
  - name: report_path
    description: Path to validation report file (default /tmp/validate-<issue>-report.md)
    required: true
---

# Transition After Validation: $ARGUMENTS.issue

## Purpose

Update Jira issue status and post the validation report based on the verdict.
This runs **inline on Opus** within the `/validate` orchestrator — do not dispatch to local.

## Phase 1: Post Validation Report

Read the report and post as a Jira comment:
```bash
report=$(cat $ARGUMENTS.report_path)
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.issue", "body": "<report content>"}'
```

## Phase 2: Apply Transition

### If verdict is TRANSITION_DONE:

1. List available transitions:
   ```bash
   npx tsx ~/.claude/skills/issues/list_transitions.ts '{"issue_key": "$ARGUMENTS.issue"}'
   ```

2. Find the "Done" transition and execute it:
   ```bash
   npx tsx ~/.claude/skills/issues/transition_issue.ts '{"issue_key": "$ARGUMENTS.issue", "transition_id": "<done-id>"}'
   ```

3. Remove the `step:validating` label, add `outcome:validated`:
   ```bash
   npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "$ARGUMENTS.issue", "update": {"labels": [{"remove": "step:validating"}, {"add": "outcome:validated"}]}}'
   ```

### If verdict is TRANSITION_TODO:

1. Transition back to "To Do":
   ```bash
   npx tsx ~/.claude/skills/issues/list_transitions.ts '{"issue_key": "$ARGUMENTS.issue"}'
   npx tsx ~/.claude/skills/issues/transition_issue.ts '{"issue_key": "$ARGUMENTS.issue", "transition_id": "<todo-id>"}'
   ```

2. Update labels:
   ```bash
   npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "$ARGUMENTS.issue", "update": {"labels": [{"remove": "step:validating"}, {"add": "outcome:validation-failed"}]}}'
   ```

### If verdict is NEEDS_DEPLOY:

1. Do NOT transition. Keep in VALIDATION.
2. Update labels:
   ```bash
   npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "$ARGUMENTS.issue", "update": {"labels": [{"remove": "step:validating"}, {"add": "step:awaiting-deploy"}]}}'
   ```
3. Post comment with deploy instructions from the validation report.
4. Report to user that deployment is needed before validation can complete.

### If verdict is NEEDS_HUMAN:

1. Do NOT transition. Add label only:
   ```bash
   npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "$ARGUMENTS.issue", "update": {"labels": [{"add": "outcome:needs-human"}]}}'
   ```

2. Report to user that manual review is needed.

## Phase 3: Output Confirmation

```
TRANSITION_RESULT:
ISSUE: $ARGUMENTS.issue
ACTION: <DONE | TODO | NEEDS_DEPLOY | NEEDS_HUMAN>
NEW_STATUS: <status after transition>
COMMENT_POSTED: true
LABELS_UPDATED: true
METRICS_STORED: true
```

## Phase 4: Store Validation Metrics

Write structured validation metrics to AgentDB for tracking accuracy over time:

```bash
npx tsx ~/.claude/skills/agentdb/pattern_store.ts '{
  "task_type": "validation-metrics",
  "approach": "validate $ARGUMENTS.issue",
  "success_rate": <1.0 if DONE, 0.0 if TODO, 0.5 if NEEDS_DEPLOY/NEEDS_HUMAN>,
  "metadata": {
    "issue": "$ARGUMENTS.issue",
    "command": "validate",
    "verdict": "<verdict>",
    "evidence_quality": "<STRONG | SUFFICIENT | INSUFFICIENT>",
    "evidence_quality_score": <1.0 | 0.7 | 0.3>,
    "runtime_tests_run": <true | false>,
    "deploy_verified": <true | false>,
    "contradiction_detected": <true | false>,
    "duration_seconds": <elapsed>,
    "captured_at": "<ISO timestamp>"
  },
  "tags": ["validation", "$ARGUMENTS.issue"]
}'
```

If the agentdb call fails, log the error but do not fail the transition — the Jira state
change is the critical operation.

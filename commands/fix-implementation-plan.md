<!-- MODEL_TIER: sonnet -->

---
description: Fix issues identified by /review-implementation-plan before implementation begins
arguments:
  - name: issue
    description: Jira issue key (e.g., PROJ-2105)
    required: true
---

> Skill reference: [session-init](.claude/skills/session-init.skill.md)

# Fix Implementation Plan: $ARGUMENTS.issue

## Purpose

This command fixes issues identified by `/review-implementation-plan` so the plan is ready for `/implement`.
It reads the review verdict from Jira comments, addresses each finding, and updates the plan.

---

## Skill Reference (MANDATORY)

**DO NOT use MCP tools. Use the Bash skill calls below.**

### IMPORTANT: Always run skills from the platform root directory
```bash
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/...
```

### Jira Skills
```bash
npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "<KEY>", "fields": "summary,description,status,labels,comment"}'
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "<KEY>", "body": "<markdown>"}'
```

### AgentDB Skills
```bash
npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "<issue> implementation plan", "top_k": 5}'
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '<json>'
```

---

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/5] Fixing critical issues...`).

---

### Phase 1: Load Review Findings

1. **Fetch Jira comments** for $ARGUMENTS.issue
2. **Find the review verdict** comment (look for "Implementation Plan Review" heading and "Verdict:" line)
3. **Parse findings** into categories: Critical, Warnings, Notes
4. **Load the original plan** from Jira comments or agentdb

If no review verdict is found, **FAIL immediately** with:
```
FAIL: No review verdict found for $ARGUMENTS.issue. Run /review-implementation-plan first.
```

If verdict is `APPROVED`, **exit early** with:
```
Plan already approved. No fixes needed. Proceed to /implement.
```

---

### Phase 2: Fix Critical Issues

For each critical finding:

1. **Understand the issue** — read relevant source code, check file paths, verify patterns
2. **Determine the fix** — what needs to change in the plan
3. **Apply the fix** — update the plan content

Common critical fixes:
- **Missing requirement coverage**: Add planned work items for uncovered requirements
- **Wrong file paths**: Verify actual repo structure and correct paths
- **Missing infrastructure**: Add DynamoDB/IAM/SQS changes to the plan
- **Architectural misalignment**: Restructure approach to match existing patterns

---

### Phase 3: Fix Warning Issues

For each warning finding:

1. **Evaluate severity** — could this cause implementation failure or just inefficiency?
2. **Apply fixes** for items likely to cause implementation failure
3. **Document decisions** for items intentionally deferred

---

### Phase 4: Update Plan Artifacts

**Plans live in Jira comments + agentdb ONLY. Do NOT write any plan files to the worktree.**

1. **Post updated plan** as a new Jira comment with heading:
   ```
   ## REVISED IMPLEMENTATION PLAN (v2)

   ### Changes from v1:
   - <change 1>
   - <change 2>

   ### Updated Plan:
   <full updated plan>
   ```

2. **Update agentdb** with the revised plan context and CGC attribution:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{
     "session_id": "${TENANT_NAMESPACE}",
     "task": "fix-implementation-plan-$ARGUMENTS.issue",
     "input": {"findings": "..."},
     "output": "plan-revised",
     "reward": 0.5,
     "success": true,
     "critique": "Fixed N critical, M warning issues",
     "metadata": {
       "fix_categories": ["wrong_path", "missing_file"],  // actual categories for THIS fix; valid values: wrong_path, missing_file, wrong_layer, missing_infra
       "cgc_caught_this": <true if any fix was identified by CGC Check A or B, false otherwise>,
       "critical_fixed": <count>,
       "warnings_fixed": <count>,
       "issue": "$ARGUMENTS.issue"
     }
   }'
   ```

3. **Clean up any plan files** that may have been written by a previous run:
   ```bash
   # Remove plan files from worktree if they exist (they should never be committed)
   worktree=$(find $PROJECT_ROOT/worktrees -maxdepth 1 -name "*$ARGUMENTS.issue*" -type d | head -1)
   if [ -n "$worktree" ]; then
     rm -f "$worktree/implementation-plan.md" "$worktree/IMPLEMENTATION_PLAN.md"
     cd "$worktree" && git rm -f implementation-plan.md IMPLEMENTATION_PLAN.md 2>/dev/null || true
   fi
   ```

---

### Phase 5: Summary

Print a structured summary:

```
## Fix Implementation Plan: $ARGUMENTS.issue

### Fixes Applied
- Critical: X/Y fixed
- Warnings: X/Y fixed (Z deferred with rationale)

### Changes Summary
- <change 1>
- <change 2>

### Status: READY_FOR_RE_REVIEW | NEEDS_ESCALATION
```

Return the status so the orchestrator can decide:
- `READY_FOR_RE_REVIEW` → re-run `/review-implementation-plan`
- `NEEDS_ESCALATION` → fundamental issues that may require re-planning from scratch

---

**START NOW: Begin Phase 1.**

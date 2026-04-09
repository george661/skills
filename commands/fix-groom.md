<!-- MODEL_TIER: sonnet -->
<!-- DISPATCH: Spawn a Task subagent with model: "sonnet" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Sonnet. -->

---
description: Fix grooming issues identified by /validate-groom. Accepts a Jira Epic key that has been groomed and validated.
arguments:
  - name: epic
    description: Jira Epic key (e.g., PROJ-123) that has been groomed and validated
    required: true
---

> Tool examples: [get_issue](.claude/skills/examples/jira/get_issue.md), [search_issues](.claude/skills/examples/jira/search_issues.md), [create_issue](.claude/skills/examples/jira/create_issue.md), [update_issue](.claude/skills/examples/jira/update_issue.md), [add_comment](.claude/skills/examples/jira/add_comment.md)
> Skill reference: [session-init](.claude/skills/session-init.skill.md)

# Fix Grooming: $ARGUMENTS.epic

This command systematically addresses validation issues identified by `/validate-groom` and corrects the grooming output.

## Prerequisites

**This command requires:**
- An Epic that has been groomed with `/groom`
- Validation results from `/validate-groom` (or known grooming issues)
- PRP document available in project-docs

**Run this AFTER `/validate-groom` reports `NEEDS_FIXES`.**

## Skill Reference (MANDATORY)

**DO NOT use MCP tools. Always run from `$PROJECT_ROOT`.**

```bash
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "<KEY>", "fields": "summary,description,status,labels,parent,issuelinks,priority,comment"}'
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "parent = <EPIC>", "fields": ["key","summary","status","labels","parent","issuelinks"]}'
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/create_issue.ts '{"project": "${PROJECT_KEY}", "issue_type": "Story", "summary": "...", "description": "...", "parent": "<EPIC>", "labels": [...], "priority": "..."}'
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "<KEY>", "parent": "<EPIC>", "labels": [...], "priority": "..."}'
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/jira/add_issue_link.ts '{"inward_issue_key": "<A>", "outward_issue_key": "<B>", "link_type": "Blocks"}'
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "<KEY>", "body": "<markdown>"}'
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "<topic>", "top_k": 5}'
```

---

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/8] Fixing coverage gaps...`).

---

### Phase 0: Initialize Session and Load Context

**[phase 0/8] Initializing...**

1. Search AgentDB for prior grooming context:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "$ARGUMENTS.epic grooming validation", "top_k": 5}'
   ```

2. Fetch the Epic:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.epic", "fields": "summary,description,status,labels,comment"}'
   ```

3. Locate the PRP:
   ```bash
   grep -rl "$ARGUMENTS.epic" "${PROJECT_ROOT}/${DOCS_REPO}/PRPs/" | head -3
   ```

4. Fetch all child issues:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "parent = $ARGUMENTS.epic ORDER BY created ASC", "fields": ["key","summary","status","labels","parent","issuelinks","priority","description"]}'
   ```

---

### Phase 1: Load Validation Report and Categorize Issues

**[phase 1/8] Loading validation report...**

1. Find the most recent "Grooming Validation Report" comment on `$ARGUMENTS.epic`.

2. **STOP** if no validation report found:
   `FAIL: No validate-groom report found for $ARGUMENTS.epic. Run /validate-groom first.`

3. **EXIT EARLY** if result is already `PASS`:
   `Grooming already validated. No fixes needed.`

4. Parse the report into fix categories:
   - `COVERAGE_GAPS` — PRP tasks with no corresponding Jira issue
   - `ORPHAN_ISSUES` — Jira issues with no PRP task mapping and not linked to Epic
   - `PARENT_LINK_ISSUES` — issues not linked to the Epic as parent
   - `DEPENDENCY_ISSUES` — missing or wrong issue links
   - `CRITERIA_ISSUES` — acceptance criteria missing or vague
   - `DUPLICATE_ISSUES` — issues covering the same PRP task

---

### Phase 2: Fix Coverage Gaps — Create Missing Issues

**[phase 2/8] Creating missing issues...**

For each task in `COVERAGE_GAPS` (PRP implementation task with no Jira issue):

1. Read the PRP task description, acceptance criteria, and dependencies
2. Determine the correct issue type (Story for implementation, Task for infrastructure/test setup)
3. Create the issue:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/create_issue.ts '{
     "project": "${PROJECT_KEY}",
     "issue_type": "Story",
     "summary": "{task summary}",
     "description": "**Acceptance Criteria:**\n- {from PRP}\n\n**PRP Task:** {PRP task reference}",
     "parent": "$ARGUMENTS.epic",
     "labels": ["step:grooming", "{tier:core|step:test|step:infra}"],
     "priority": "{High|Medium|Low based on PRP tier}"
   }'
   ```
4. Record the new issue key for dependency linking in Phase 4.

**Priority mapping from PRP tiers:**
- Tier 1 (core) → High
- Tier 2 (standard) → Medium
- Tier 3 (test/polish) → Low

---

### Phase 3: Fix Parent Link Issues

**[phase 3/8] Fixing parent links...**

For each issue in `PARENT_LINK_ISSUES` (issue not linked to Epic as parent):

1. Check the current parent field and issue status
2. Update parent:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "<CHILD_KEY>", "parent": "$ARGUMENTS.epic"}'
   ```
3. Verify the update was applied by re-fetching the issue.

**Note:** Jira may reject parent updates for issues in Done status. If rejected, add a comment to the Epic noting the orphaned issue and its resolution status instead.

---

### Phase 4: Fix Dependency Issues

**[phase 4/8] Fixing dependency links...**

For each item in `DEPENDENCY_ISSUES` (PRP dependency not reflected as a Jira issue link):

1. Identify the two issue keys that should be linked
2. Determine the link direction: A blocks B, or B depends on A
3. Create the link:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/jira/add_issue_link.ts '{
     "inward_issue_key": "<BLOCKED_ISSUE>",
     "outward_issue_key": "<BLOCKING_ISSUE>",
     "link_type": "Blocks"
   }'
   ```

**Common link types:** `Blocks`, `Cloners`, `Duplicate`, `Relates`

---

### Phase 5: Fix Acceptance Criteria Issues

**[phase 5/8] Fixing acceptance criteria...**

For each issue in `CRITERIA_ISSUES`:

1. Read the original PRP task acceptance criteria
2. Check whether the issue description already contains them verbatim
3. Update the issue description to include the criteria:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/update_issue.ts '{
     "issue_key": "<KEY>",
     "description": "**Acceptance Criteria:**\n- {criterion 1 — binary-testable}\n- {criterion 2}"
   }'
   ```

Rewrite vague criteria ("works correctly", "is fast") into binary-testable form:
- BAD: "the page loads quickly"
- GOOD: "the page loads in < 2s on a 3G connection (measured by Chrome DevTools)"

---

### Phase 6: Resolve Duplicates and Orphans

**[phase 6/8] Resolving duplicates and orphans...**

For each pair in `DUPLICATE_ISSUES`:
1. Determine which issue to keep (prefer the more complete description)
2. Link as duplicate:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/jira/add_issue_link.ts '{"inward_issue_key": "<KEEP>", "outward_issue_key": "<REMOVE>", "link_type": "Duplicate"}'
   ```
3. Transition the duplicate issue to Backlog or Won't Do and add a comment explaining it's a duplicate.

For true orphans (issues under the Epic that map to nothing in the PRP):
- If the work is needed: add a brief PRP note and keep the issue
- If the work is NOT needed: comment explaining the rationale, transition to Backlog

---

### Phase 7: Update Epic and Re-validate

**[phase 7/8] Updating Epic and re-validating...**

1. Update Epic labels to reflect the fix was applied:
   ```bash
   # Read current labels first
   CURRENT_LABELS=$(cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.epic", "fields": "labels"}' | python3 -c "import json,sys; d=json.load(sys.stdin); lbls=[l for l in d.get('labels',[]) if l != 'fix-groom-needed']; print(json.dumps(lbls))")
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/update_issue.ts "{"issue_key": "$ARGUMENTS.epic", "labels": $CURRENT_LABELS}"
   ```

2. Post a summary comment:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/add_comment.ts '{
     "issue_key": "$ARGUMENTS.epic",
     "body": "## Grooming Fix Applied\n\n### Fixed\n- Coverage gaps: {N} issues created\n- Parent links: {M} corrected\n- Dependencies: {P} links added\n- Acceptance criteria: {Q} issues updated\n\n**Next step:** Run `/validate-groom $ARGUMENTS.epic` to confirm."
   }'
   ```

3. Store episode in AgentDB:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{
     "session_id": "${TENANT_NAMESPACE}", "task": "fix-groom-$ARGUMENTS.epic",
     "output": "groom-fixed", "reward": 0.7, "success": true,
     "critique": "Fixed N coverage gaps, M parent links, P dependencies"
   }'
   ```

4. Re-run validate-groom:
   - Dispatch `/validate-groom $ARGUMENTS.epic`
   - If PASS → `READY: Grooming validated. Epic ready for sprint planning.`
   - If FAIL → `NEEDS_ESCALATION: {N} issues remain. See latest validate-groom report.`

---

### Phase 8: Summary

**[phase 8/8] Summary**

```
## Fix Grooming: $ARGUMENTS.epic

### Issues Created: {N}
### Parent Links Fixed: {M}
### Dependency Links Added: {P}
### Acceptance Criteria Updated: {Q}
### Duplicates Resolved: {R}

### Status: READY | NEEDS_ESCALATION
```

**START NOW: Begin Phase 0.**

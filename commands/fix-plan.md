<!-- MODEL_TIER: sonnet -->
<!-- DISPATCH: Spawn a Task subagent with model: "sonnet" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Sonnet. -->

---
description: Fix plan validation issues identified by /validate-plan
aliases: [fix-prp]
arguments:
  - name: input
    description: Jira Epic key (e.g., PROJ-123) or path to local plan file
    required: true
---

> Tool examples: [get_issue](.claude/skills/examples/jira/get_issue.md), [add_comment](.claude/skills/examples/jira/add_comment.md), [list_comments](.claude/skills/examples/jira/list_comments.md)
> Skill reference: [session-init](.claude/skills/session-init.skill.md)

# Fix Plan: $ARGUMENTS.input

This command systematically addresses validation issues identified by `/validate-plan` and updates the plan document.

## Prerequisites

**This command requires:**
- A plan that has been validated with `/validate-plan` (or validation issues you want to address)
- Access to project-docs repository for committing fixes

**Input Detection:**
- If `$ARGUMENTS.input` starts with a project prefix → treat as Jira Epic key
- If `$ARGUMENTS.input` contains `/` or ends with `.md` → treat as file path

## Skill Reference (MANDATORY)

**DO NOT use MCP tools. Use the Bash skill calls below. Always run from `$PROJECT_ROOT`.**

```bash
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "<KEY>", "fields": "summary,description,status,labels,comment"}'
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "<KEY>", "body": "<markdown>"}'
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "<topic>", "top_k": 5}'
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '<json>'
```

---

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/8] Fixing critical issues...`).

---

### Phase 0: Initialize Session and Detect Input

**[phase 0/8] Initializing...**

1. Search AgentDB for prior plan validation context:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "$ARGUMENTS.input PRP validation", "top_k": 5}'
   ```

2. Detect input type:
   - If `$ARGUMENTS.input` starts with a project prefix → fetch Epic from Jira; look for "PRP Validation Report" comment
   - If `$ARGUMENTS.input` ends with `.md` or contains `/` → treat as PRP file path directly

3. Fetch Epic and scan comments for the validation report:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.input", "fields": "summary,description,status,labels,comment"}'
   ```

4. Extract: `EPIC_KEY`, `PRP_PATH`, and the most recent "PRP Validation Report" comment body.

---

### Phase 1: Load PRP and Validation Feedback

**[phase 1/8] Loading PRP and validation report...**

1. Read the PRP file:
   ```bash
   cat "${PROJECT_ROOT}/${DOCS_REPO}/PRPs/[path]/PRP-XXX-{slug}.md"
   # or search:
   grep -rl "$ARGUMENTS.input" "${PROJECT_ROOT}/${DOCS_REPO}/PRPs/" | head -3
   ```

2. **STOP** if no PRP found:
   `FAIL: No PRP found for $ARGUMENTS.input. Run /plan first.`

3. **STOP** if no validation report found:
   `FAIL: No validation report found. Run /validate-plan $ARGUMENTS.input first.`

4. Parse the validation report into:
   - `BLOCKING_ISSUES` — items marked BLOCKING or listed under "Blocking Issues"
   - `WARNINGS` — items marked WARNING
   - `NOTES` — minor notes

5. **EXIT EARLY** if result is already `PASS` with zero blocking issues:
   `Plan already validated. Proceed to /groom $ARGUMENTS.input.`

---

### Phase 2: Analyze and Categorize Issues

**[phase 2/8] Categorizing issues...**

Group blocking issues by type:

| Type | Description | Fix Strategy |
|---|---|---|
| `missing_section` | Required PRP section absent | Add section with correct content |
| `design_misaligned` | PRP contradicts design session | Reconcile with design session state.json |
| `missing_test_section` | e2e-tests/lambda-functions/frontend-app Pact section absent | Add test section per TESTING.md |
| `wrong_scope` | Repo listed in Affects with no tasks or criteria | Add tasks and acceptance criteria |
| `vague_criteria` | Acceptance criteria not binary-testable | Rewrite with specific pass/fail conditions |
| `deferred_included` | PRP includes work explicitly deferred in design | Remove or move to Open Questions |
| `missing_task` | Implementation task missing for a contract/domain change | Add task |

---

### Phase 3: Fix Blocking Issues

**[phase 3/8] Fixing blocking issues...**

For each item in `BLOCKING_ISSUES`:

1. Re-read the relevant PRP section and the validation finding
2. Determine the correct fix — check design session state.json, TESTING.md, CLAUDE.md as needed
3. Edit the PRP file in-place:
   - Add missing sections
   - Correct wrong scope
   - Add test sub-sections with explicit file names and run commands
   - Rewrite vague criteria to be binary-testable
   - Remove deferred decisions from scope

For design misalignment — read the design session state:
```bash
cat "${DESIGN_DOCS_PATH}/sessions/${DESIGN_SESSION_ID}/state.json"
```
Reconcile PRP problem statement, repo scope, and invariants with the design outputs.

For missing lambda-functions test section — add:
```markdown
### lambda-functions Tests
- Unit: `functions/{name}/main_test.go` — cover happy path, error cases
- Hurl: `tests/hurl/{domain}.hurl` — smoke test against dev endpoint
- Integration: `tests/integration/integration_test.go` — if cross-function flow involved
- Run: `cd lambda-functions && go test ./functions/{name}/... -v`
```

For missing e2e-tests test section — add:
```markdown
### e2e-tests Tests
- Journey spec: `tests/journeys/{domain}.spec.ts`
- Page objects: `pages/{PageName}.ts`
- test-ids: `src/test-ids.ts` — add `{FEATURE}_{ELEMENT}` or "none"
- Run: `npx playwright test tests/journeys/{domain}.spec.ts --project=chromium`
```

For missing frontend-app Pact section — add:
```markdown
### frontend-app Tests
- Pact consumer contract: `pact/consumers/{feature}.pact.spec.ts`
- Vitest unit tests: `src/{component}.test.tsx`
- MANDATORY: `npm run test:pact` must pass before PR merge
```

---

### Phase 3.5: Fix Security Audit Findings

**[phase 3.5/8] Fixing security findings...**

For each security finding:
- **Unauthenticated endpoint**: Add acceptance criterion verifying auth
- **PII without encryption**: Add KMS encryption task and AC
- **Missing IAM**: Add DynamoDB/S3/SQS permission task to implementation tasks
- **OWASP concern**: Add input validation requirement to acceptance criteria

---

### Phase 4: Fix Warnings

**[phase 4/8] Fixing warnings...**

For each warning:
1. Could this cause implementation failure? If yes: fix it
2. If no: add a Decision Log entry explaining deferral

Common warnings:
- **Non-objective criteria**: Rewrite with measurable thresholds ("< 2s", "returns 200")
- **Design session not referenced**: Add `**Design Session**: {session_id}` to PRP header
- **Wireframe coverage gap**: Add an acceptance criterion per wireframed screen

---

### Phase 5: Fix Minor Notes

**[phase 5/8] Addressing notes...**

For each note: fix directly if trivial (typo, missing link), or add to Decision Log if deferring.

---

### Phase 6: Commit and Update Epic

**[phase 6/8] Committing updated PRP...**

1. Commit the updated PRP:
   ```bash
   cd "${PROJECT_ROOT}/${DOCS_REPO}" && git add PRPs/
   git commit -m "fix($ARGUMENTS.input): address PRP validation blocking issues"
   git push origin main
   ```

2. Post a summary comment to the Epic:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/add_comment.ts '{
     "issue_key": "$ARGUMENTS.input",
     "body": "## PRP Fix Applied\n\n### Blocking Issues Fixed\n- {list}\n\n### Warnings Fixed\n- {list}\n\n**Next step:** Run `/validate-plan $ARGUMENTS.input` to re-validate."
   }'
   ```

3. Store episode in AgentDB:
   ```bash
   cd $PROJECT_ROOT && npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{
     "session_id": "${TENANT_NAMESPACE}", "task": "fix-plan-$ARGUMENTS.input",
     "output": "prp-fixed", "reward": 0.7, "success": true,
     "critique": "Fixed N blocking, M warnings in PRP"
   }'
   ```

---

### Phase 7: Re-validate

**[phase 7/8] Re-validating...**

Dispatch `/validate-plan $ARGUMENTS.input` inline.

- **PASS** → `READY: PRP validated. Run /groom $ARGUMENTS.input.`
- **FAIL** → `NEEDS_ESCALATION: {N} blocking issues remain. See latest validation report.`

---

### Phase 8: Summary

**[phase 8/8] Summary**

```
## Fix Plan: $ARGUMENTS.input

### Fixes Applied
- Blocking: X fixed, Y deferred
- Warnings: X fixed, Y deferred

### Status: READY | NEEDS_ESCALATION
```

**START NOW: Begin Phase 0.**

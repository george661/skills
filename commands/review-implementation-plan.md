<!-- MODEL_TIER: opus -->
<!-- No dispatch needed - this command executes directly on the session model (Opus). -->
<!-- This is a quality gate — it requires strong judgment to evaluate plan completeness. -->

---
description: Review an implementation plan created by /create-implementation-plan before handing off to /implement
arguments:
  - name: issue
    description: Jira issue key (e.g., PROJ-2105)
    required: true
---

> Skill reference: [session-init](.claude/skills/session-init.skill.md)

# Review Implementation Plan: $ARGUMENTS.issue

## Purpose

This command is a **quality gate** between `/create-implementation-plan` and `/implement` in the `/work` pipeline.
It catches plan deficiencies **before** a local model burns 10-15 minutes on a flawed implementation.

**Common issues this catches:**
- Plan scope doesn't match Jira requirements
- Wrong repo or missing multi-repo awareness
- Missing or inadequate test strategy
- Files listed that don't exist or wrong paths
- Architectural misalignment (e.g., adding REST endpoints when the domain uses events)
- Missing infrastructure changes (DynamoDB tables, IAM roles, SQS queues)
- Validation criteria that are untestable or incomplete
- **No committable artifact** — plans that only say "verify X is already done" with no code change will cause `/implement` to fail (nothing to commit → no PR). If the issue turns out to be a false positive, the plan must include a minimal committable change (e.g., a doc comment, a test assertion, a JSDoc header) to keep the PR workflow intact.

---

## Skill Reference (MANDATORY)

**DO NOT use MCP tools. Use the Bash skill calls below.**

### IMPORTANT: Always run skills from the platform root directory
```bash
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/...
```

### Jira Skills
```bash
# Get issue with all fields
npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "<KEY>", "fields": "summary,description,status,labels,comment"}'

# Add comment
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "<KEY>", "body": "<markdown>"}'
```

### AgentDB Skills
```bash
# Recall implementation plan context
npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "<issue> implementation plan", "top_k": 5}'
```

---

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/6] Checking scope alignment...`).

---

### Phase 1: Load Context

Gather all plan artifacts in parallel:

1. **Jira issue** — get full details including description, acceptance criteria, comments (the plan is posted as a comment)
2. **AgentDB** — recall any stored implementation plan context
3. **Worktree context file** — read `.agent-context.json` from the worktree if it exists

```bash
# Parallel:
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "summary,description,status,labels,comment"}'
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "$ARGUMENTS.issue implementation plan", "top_k": 5}'
```

Find the implementation plan comment in the Jira comments (look for "IMPLEMENTATION PLAN" or similar heading).

If no plan is found, **FAIL immediately** with:
```
FAIL: No implementation plan found for $ARGUMENTS.issue. Run /create-implementation-plan first.
```

---

### Phase 2: Validate Scope Alignment

Compare the plan against the Jira issue requirements:

1. **Extract requirements** from the issue description and acceptance criteria
2. **Extract planned work** from the implementation plan
3. **Check coverage**: Every requirement must map to planned work
4. **Check scope creep**: Every planned item must trace back to a requirement (flag extras)
5. **Field-level check**: When the AC enumerates specific fields/properties (e.g., struct fields, API params, DB columns), verify the plan lists each one. Also read the repo's `CLAUDE.md` for struct/field rules — repos like go-common require verbatim field reproduction.

**Output a checklist:**
```
Scope Alignment:
  [PASS] Requirement: "Users can request account deletion" → Planned: request-deletion handler
  [PASS] Requirement: "30-day grace period" → Planned: cancel-deletion handler + TTL
  [WARN] Planned: "Email notification service" → No explicit requirement (scope creep?)
  [FAIL] Requirement: "Admin can force-delete" → Not covered in plan
```

---

### Phase 3: Validate Technical Approach

Read actual source code to verify the plan's assumptions:

1. **Verify file paths** — Do the files the plan references actually exist? Are new files in the right directories?
2. **Check patterns** — Does the plan follow existing patterns in the repo? (e.g., handler structure, service patterns, test patterns)
3. **Verify dependencies** — Are imports/packages the plan assumes available actually in go.mod/package.json?
4. **Multi-repo check** — If the plan spans repos, are all repos identified with specific changes?
5. **Committable artifact check** — Does the plan result in at least one file being modified or created? A plan whose entire implementation is "run tests and confirm they pass" is **CRITICAL: FAIL**. `/implement` requires a commit to create a PR. If the underlying issue is already resolved (false positive), require the plan to add a minimal change such as a doc comment, a verification test assertion, or a JSDoc header documenting the finding. Flag any "verify-only" plan as `NEEDS_FIXES` with this explicit requirement.

```bash
# Check if worktree exists and verify file structure
ls $PROJECT_ROOT/worktrees/*-$ARGUMENTS.issue/ 2>/dev/null
```

Read 2-3 existing files in the same domain to understand patterns the new code should follow.

---

### Phase 3.5: CGC Verification

**Best-effort — failure degrades gracefully, never blocks verdict.**

#### CGC Health Check

```bash
# 1. Binary check
CGC_AVAILABLE=true
command -v cgc >/dev/null 2>&1 || { CGC_AVAILABLE=false; }

# 2. Neo4j check + auto-start
if [[ "$CGC_AVAILABLE" == "true" ]]; then
  docker ps --filter name=neo4j --format '{{.Status}}' 2>/dev/null | grep -q "Up" || {
    docker start neo4j 2>/dev/null && sleep 5
  }
  # 3. Connectivity check
  export DEFAULT_DATABASE=neo4j
  cgc list 2>&1 | grep -q "Project" || { CGC_AVAILABLE=false; }
fi
```

If `CGC_AVAILABLE=false`: append `CGC Verification: skipped (Neo4j unavailable)` to the verdict and proceed to Phase 4. No verdict change. If CGC is unavailable: run `/index-repos` to diagnose. Check `docker ps` for Neo4j.

#### Check A — Path Existence

For each file in the plan's "Files to Change", search for the primary function or type name in that file using:

```
mcp__CodeGraphContext__find_code
  query: "<function or type name from plan entry>"
```

| Result | Verdict tag |
|--------|-------------|
| 0 results | `[FAIL] — function not found in graph, likely wrong path` |
| Found at different path | `[WARN] — path drift: CGC finds it at <actual path>` |
| Found at expected path | `[PASS]` |

Any `[FAIL]` → auto-escalate overall verdict to `NEEDS_FIXES`.

#### Check B — Blast Radius Completeness

For the plan's primary entry point function, run:

```
mcp__CodeGraphContext__analyze_code_relationships
  query_type: "find_callers"
  function_name: "<primary entry point>"
```

Each caller NOT in the plan's file list → `[WARN] potential missed impact`.

`[WARN]` only items: record in verdict; reviewer decides whether to escalate.

#### CGC Verdict Output

Append to the verdict under `### CGC Verification`:

```
### CGC Verification
  [PASS] lambda-functions/functions/sessions/main.go — HandleCreateSession found
  [FAIL] go-common/db/sessions.go — CreateSession not found (wrong path?)
  [WARN] lambda-functions/functions/session-purchases/main.go — calls HandleCreateSession, not in plan
```

Or if unavailable: `CGC Verification: skipped (Neo4j unavailable)`

#### Check C — Wiring Verification

For each NEW file the plan creates (components, routes, endpoints, Lambda handlers):

1. Search the plan for import/registration steps that connect the new file to existing code
2. If CGC available: `mcp__CodeGraphContext__find_code` to verify the import target exists
3. If a new file has NO import/registration step in the plan: `[FAIL] New file {path} created but never imported or registered`

For each MODIFIED file:
1. `mcp__CodeGraphContext__analyze_code_relationships` to find all dependents
2. If any dependent is NOT mentioned in the plan: `[WARN] {dependent} imports {modified_file} but is not in the plan`

**CGC false positive override**: If the plan documents a dynamic import or runtime registration (e.g., plugin system, string-based require), the agent may override with explicit justification. Log override in AgentDB.

#### Check D — Documentation Cross-Reference

1. Read TESTING.md Pre-Commit Checklist from the target repo
2. Verify the plan includes ALL prescribed pre-commit steps (lint, typecheck, unit tests, etc.)
3. If any prescribed step is missing from the plan: `[FAIL] TESTING.md requires {step} but plan does not include it`

4. Read VALIDATION.md Evidence Requirements from the target repo
5. Verify the plan's validation section matches the repo's evidence requirements
6. If mismatch: `[WARN] VALIDATION.md requires {evidence_type} but plan validation section does not mention it`

---

### Phase 4: Validate Test Strategy

1. **Test types covered** — Unit, integration, e2e as appropriate for the issue type
2. **Test scenarios** — Are edge cases covered? Error paths? Auth checks?
3. **Validation criteria** — Are they concrete and automatable (not vague like "works correctly")?
4. **Existing test patterns** — Does the test plan follow the repo's TESTING.md conventions?

---

### Phase 5: Validate Infrastructure & Dependencies

1. **Infrastructure changes** — Are all needed DynamoDB tables, IAM roles, SQS queues, etc. identified?
2. **API Gateway routes** — Are new endpoints properly planned in serverless.yml or terraform?
3. **Environment variables** — Are new env vars documented?
4. **Cross-service dependencies** — Are downstream impacts identified?

---

### Phase 6: Verdict

Produce a structured verdict:

```
## Implementation Plan Review: $ARGUMENTS.issue

### Verdict: APPROVED | NEEDS_FIXES | REJECTED

### Summary
<1-2 sentence overall assessment>

### Findings

#### Critical (must fix before implementation)
- <finding with specific fix needed>

#### Warnings (should fix, risk of wasted implementation time)
- <finding with recommendation>

#### Notes (informational, no action required)
- <observation>

### Scope Coverage: X/Y requirements covered
### Test Coverage: <adequate|gaps identified>
### Technical Approach: <sound|concerns identified>
### CGC Verification: <summary line or "skipped (Neo4j unavailable)">
```

### MANDATORY: Post Verdict to Jira

**You MUST post the verdict as a Jira comment BEFORE returning.** This is not optional.
The `/fix-implementation-plan` command reads the verdict from Jira comments — if you skip
this step, the fix command will fail with "No review verdict found."

```bash
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.issue", "body": "<the full verdict markdown above>"}'
```

**Verify the comment was posted** — check the response for a valid `id` field.

### MANDATORY: Store Episode in AgentDB

After posting the Jira comment, store the outcome so NEEDS_FIXES rate can be tracked:

```bash
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{
  "session_id": "${TENANT_NAMESPACE}",
  "task": "review-implementation-plan-$ARGUMENTS.issue",
  "input": {},
  "output": "verdict-posted",
  "reward": 1.0,
  "success": <true if APPROVED, false otherwise>,
  "critique": "Verdict: <APPROVED|NEEDS_FIXES|REJECTED>",
  "metadata": {
    "verdict": "<APPROVED|NEEDS_FIXES|REJECTED>",
    "cgc_available": <true|false>,
    "cgc_failures": <count of [FAIL] items>,
    "cgc_warnings": <count of [WARN] items>,
    "issue": "$ARGUMENTS.issue"
  }
}'
```

**Return the verdict** so the orchestrator can decide next steps:
- `APPROVED` → proceed to `/implement`
- `NEEDS_FIXES` → dispatch `/fix-implementation-plan`
- `REJECTED` → re-run `/create-implementation-plan` with feedback

---

**START NOW: Begin Phase 1.**

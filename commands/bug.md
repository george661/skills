<!-- MODEL_TIER: sonnet -->
<!-- DISPATCH: Spawn a Task subagent with model: "sonnet" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Sonnet. -->

---
description: Report a bug with evidence collection, reproduction steps, and root cause hypothesis - creates Jira issue (does NOT prescribe fixes)
arguments:
  - name: description
    description: Brief description of the bug or problem encountered
    required: true
  - name: pipeline_url
    description: URL to the failed pipeline (for pipeline-triggered bugs)
    required: false
  - name: source_issue
    description: Source issue key that triggered this bug (e.g., PROJ-123 whose pipeline failed)
    required: false
  - name: repository
    description: Repository where the pipeline failed
    required: false
---

> Tool examples: [search_issues](.claude/skills/examples/jira/search_issues.md), [get_issue](.claude/skills/examples/jira/get_issue.md), [create_issue](.claude/skills/examples/jira/create_issue.md), [add_comment](.claude/skills/examples/jira/add_comment.md), [update_issue](.claude/skills/examples/jira/update_issue.md), [list_transitions](.claude/skills/examples/jira/list_transitions.md), [transition_issue](.claude/skills/examples/jira/transition_issue.md)

# Bug Report Workflow: $ARGUMENTS.description

## Overview

This command systematically documents a bug by:

1. Collecting evidence (logs, screenshots, error messages)
2. Documenting clear reproduction steps
3. Forming a root cause hypothesis with investigation areas
4. Creating a Jira Bug issue with all details
5. Transitioning the issue to To Do
6. **Creating failing test(s)** in affected repo(s) — committed and pushed with smart commits
7. **Linking regressions** to original bug/feature/epic for traceability
8. **[Pipeline Mode]** Linking to source issue and managing pipeline-blocked state

## ⚠️ CRITICAL: Do NOT Prescribe Fixes

**Bug reports document what is broken, NOT how to fix it.** The `/bug` command produces:
- Evidence of the problem
- Steps to reproduce
- A root cause **hypothesis** (what is likely wrong)
- **Investigation areas** (what needs to be examined further)

**The `/bug` command does NOT produce:**
- Specific code changes or implementation steps
- A "fix plan" or "proposed fix"
- Complexity estimates for a fix

**Why:** A bug report captures a snapshot of a problem with limited investigation. The agent may not understand the full architectural context, cross-repo implications, or design decisions behind the code. Prescribing a fix prematurely can lead to wrong solutions that ignore broader system design. The fix is determined later during `/work` or `/plan` when the full context is available.

## ⚠️ CRITICAL: Context Management for Pipeline Mode

**When `$ARGUMENTS.pipeline_url` is provided (automated pipeline bugs):**
- **SKIP** Phase 0.2 (episodic memory search) - adds ~30K tokens
- **SKIP** Phase 0.3 (text-match bug search) - 0.5.5 covers repo bugs by label
- **SKIP** Phase 1 AskUserQuestion - not interactive
- **SKIP** Phase 2 browser evidence collection - not a UI bug
- **SKIP** Phase 3 AskUserQuestion - not interactive
- **SKIP** Phase 4.1 Skill + Task agent - adds ~50K tokens
- **LIMIT** searches to 10 issues max, summaries only (no descriptions)
- **LIMIT** pipeline logs to errors_only with max_lines: 100

**Target: Complete pipeline bugs within 50K tokens to avoid "Input too long" errors.**

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

1. Phase 0: Load memory, search for related bugs
2. Phase 0.5: [Pipeline Mode] Extract failure context + get ALL repo issues
3. Phase 0.5.7: [Pipeline Mode] Decide: update existing OR create new bug
4. Phase 1: Gather bug context from user description
5. Phase 2: Collect evidence (logs, screenshots, errors)
6. Phase 3: Document reproduction steps
7. Phase 4: Analyze root cause and identify investigation areas
7.5. Phase 4.5: Duplicate Detection Gate
8. Phase 5: Create Jira Bug issue with all details
9. Phase 6: Transition issue and link to source
10. Phase 6.2: Failing Test Gate (MANDATORY) — create worktrees, write failing tests, commit and push
11. Phase 6.5: Validate created bug issue
12. Phase 6.7: Consolidation Check (creation-time hint)

**START NOW: Begin Phase 0/Step 0.**
---

---

## Phase 4.5: Duplicate Detection Gate (MANDATORY)

**[phase 4.5] Checking for duplicate bug reports...**

> Skip this phase when `$ARGUMENTS.pipeline_url` is set (pipeline/automation mode).

Before creating the Jira bug issue, search for existing bugs that match:

### Step 1: Search Jira for Similar Bugs

Extract 2-3 key terms from the bug description and search:

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${TENANT_PROJECT} AND issuetype = Bug AND summary ~ "keyword1" AND summary ~ "keyword2" AND status != Done", "fields": ["key", "summary", "status", "priority"], "max_results": 10}'
```

### Step 2: Search AgentDB for Similar Patterns

```bash
npx tsx ~/.claude/skills/agentdb/pattern_search.ts '{"task": "{bug_summary}", "k": 5}'
```

### Step 3: Evaluate Matches

If matches are found with similarity > 0.7 (based on summary overlap, same repo, same error):

1. Present matches to user:
   ```
   Potential duplicate bugs found:
     - {key}: {summary} (status: {status})
     - {key}: {summary} (status: {status})
   Is this a duplicate of any of these? [Y/N]
   ```

2. If user confirms duplicate (Y):
   - Add a comment on the existing bug with new evidence collected
   - Link to the existing issue instead of creating a new one
   - STOP -- do not create a new bug issue

3. If user says not a duplicate (N):
   - Store the relationship in AgentDB to avoid re-flagging:
     ```bash
     npx tsx ~/.claude/skills/agentdb/pattern_store.ts '{"task_type": "dedup-declined", "approach": "{new_summary} vs {existing_key}", "success_rate": 0}'
     ```
   - Proceed with bug creation

4. If no matches found: proceed with bug creation.

## Phase 6.2: Failing Test Gate (MANDATORY)

**[phase 6.2] Creating failing tests for bug reproduction...**

Every bug MUST have at least one failing test committed before the bug report is complete. This test:
- Asserts the CORRECT behavior (what should work when the bug is fixed)
- FAILS right now because the bug is present
- Becomes the canonical acceptance criterion — the fix MUST make it pass

**CRITICAL: A test that fails because the test code is broken is NOT a valid failing test.
The test code itself must be correct — only the behavior under test is broken.**

### Step 1: Determine affected repos and test strategy

From the root cause analysis (Phase 4), identify which repo(s) contain the broken code
and what type of test is most appropriate:

| Repo Type | Test Type | Test Location Pattern |
|-----------|-----------|----------------------|
| Go Lambda (lambda-functions) | Unit test | `{function}/handler_test.go` or `{function}/{module}_test.go` |
| Go library (go-common) | Unit test | `{package}/{module}_test.go` |
| React frontend (frontend-app) | Component/integration test | `src/**/__tests__/*.test.tsx` |
| Playwright (e2e-tests) | E2E spec | `$E2E_TEST_DIR/issues/{BUG-KEY}.spec.ts` |
| Go Lambda (auth-service) | Unit test | `lambda/{function}/*_test.go` |
| Terraform (core-infra) | Plan validation | `tests/*.tftest.hcl` |
| React (dashboard) | Component test | `src/**/__tests__/*.test.tsx` |

**Multiple repos may be affected.** Create tests in each one that exercises the broken path.

If `$E2E_REPO` is set AND the bug is observable via UI, also create an E2E spec using
`/e2e-write` (using the bug issue key). This provides browser-level regression coverage
in addition to unit/integration tests.

### Step 2: Create git worktrees for each affected repo

For each affected repo, create a worktree named with the bug's issue key:

```bash
cd $PROJECT_ROOT/<repo>
git fetch origin main
git worktree add $PROJECT_ROOT/worktrees/<repo>/{BUG-KEY}-failing-tests -b {BUG-KEY}-failing-tests origin/main
cd $PROJECT_ROOT/worktrees/<repo>/{BUG-KEY}-failing-tests
npm install 2>/dev/null || go mod download 2>/dev/null || true
```

### Step 3: Write failing test(s)

Read the repo's TESTING.md first to understand existing test patterns and helpers.

Write test(s) that assert the correct behavior. Each test MUST:
- Have a clear name: `Test_<expected_behavior>` (Go) or `it('should <expected behavior>')` (JS/TS)
- Include a comment: `// Regression test for {BUG-KEY}: {one-line bug summary}`
- Use existing test patterns and helpers from the repo
- Test ONLY the broken behavior — keep it minimal and focused

### Step 4: Run tests and verify expected failure

Run ONLY the new test(s), not the full suite:

```bash
# Go:
go test -run Test<BugKeyDescription> ./path/to/package/ -v

# TypeScript/Jest:
npx jest --testPathPattern="<test-file>" --no-coverage

# Playwright:
npx playwright test <test-file> --reporter=list
```

**Verify the failure is expected:**

| Result | Action |
|--------|--------|
| Test fails with expected symptom (e.g., "expected 200 got 500") | Correct — proceed to Step 5 |
| Test fails for unexpected reason (compilation error, missing import) | Fix the test code — the test itself must be valid |
| Test PASSES | The bug may already be fixed. Investigate: re-read the bug evidence, check if a recent commit resolved it. If confirmed fixed, update the Jira bug and STOP. |

### Step 5: Commit and push with smart commits

```bash
cd $PROJECT_ROOT/worktrees/<repo>/{BUG-KEY}-failing-tests
git add -A
git commit -m "$(cat <<'EOF'
{BUG-KEY} add failing regression test

Test asserts correct behavior that is currently broken.
Expected to pass once {BUG-KEY} is resolved.
EOF
)"
git push -u origin {BUG-KEY}-failing-tests
```

The smart commit format (`{BUG-KEY}` at the start) ensures Jira auto-links the commit and branch.

### Step 6: Update Jira acceptance criteria

Add a comment to the bug issue documenting the test locations and making them
part of the acceptance criteria:

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{
  "issue_key": "{BUG-KEY}",
  "body": "h3. Failing Regression Test(s) Created\n\n||Repo||Branch||Test File||Expected Failure||\n|<repo>|{BUG-KEY}-failing-tests|<test-path>|<expected failure description>|\n\n*Acceptance criteria:* These test(s) MUST pass when the fix is complete. The /work command will verify this."
}'
```

### Step 7: Regression traceability linking

If the bug description, evidence, or root cause references an original feature or prior bug:

1. Search for the original issue:
   ```bash
   npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${TENANT_PROJECT} AND key = <referenced-key>", "fields": ["key", "summary", "issuetype", "parent"]}'
   ```

2. Create Jira issue link for regression traceability:
   ```bash
   npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "{BUG-KEY}", "update": {"issuelinks": [{"add": {"type": {"name": "Relates"}, "outwardIssue": {"key": "<original-key>"}}}]}}'
   ```

3. If the original issue has a parent epic, also link the bug to the epic:
   ```bash
   npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "{BUG-KEY}", "update": {"issuelinks": [{"add": {"type": {"name": "Relates"}, "outwardIssue": {"key": "<epic-key>"}}}]}}'
   ```

4. If this is a REGRESSION of a previously-fixed bug, use "is caused by" link type instead of "Relates":
   ```bash
   npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "{BUG-KEY}", "update": {"issuelinks": [{"add": {"type": {"name": "Problem/Incident"}, "outwardIssue": {"key": "<original-bug-key>"}}}]}}'
   ```

---

## Phase 6.7: Consolidation Check (Creation-Time Hint)

**[phase 6.7/11] Checking for consolidation opportunities...**

> Skip this phase when `$ARGUMENTS.pipeline_url` is set (pipeline/automation mode).

```bash
# Skip in pipeline/automation mode
[[ "${CLAUDE_IS_PIPELINE:-}" == "true" ]] && echo "pipeline mode — skipping consolidation check" && exit 0

CACHE_DIR="${HOME}/.cache/garden"
if [[ -f "${CACHE_DIR}/issues/index.json" ]]; then
  cache_age_check=$(python3 -c "
import json, os, time
meta_path = os.path.expanduser('~/.cache/garden/cache-meta.json')
if not os.path.exists(meta_path): print('stale'); exit()
meta = json.load(open(meta_path))
created = meta.get('createdAt', '')
if not created: print('stale'); exit()
import datetime
age = time.time() - datetime.datetime.fromisoformat(created.replace('Z','+00:00')).timestamp()
print('fresh' if age < 14400 else 'stale')  # 4h TTL
")
  if [[ "$cache_age_check" == "fresh" ]]; then
    echo "Checking for consolidation opportunities..."
    # Search index.json for open issues in the same repository or module
    # referenced in the new bug issue's description
  fi
fi
```

If candidates found in the same repository or module path:
1. Present suggestion: "PROJ-XXX and NEW-KEY both touch `{module/path}` — consider working them in a single PR"
2. Ask user:
   - **Confirm** → add `consolidate-with:PROJ-XXX` label to both issues + add a cross-link comment on each
   - **Decline** → store the declination in AgentDB:
     ```bash
     npx tsx ~/.claude/skills/agentdb/pattern_store.ts '{
       "task_type": "consolidation-decline:PROJ-XXX:NEW-KEY",
       "approach": "declined",
       "success_rate": 0
     }'
     ```
3. If no cache present, no candidates found, or pipeline mode: skip silently

---

## Pattern Learning Integration

**Bug reporting patterns are stored in agentdb for future reference.**

Store completion in memory:
```bash
npx tsx ~/.claude/skills/agentdb/pattern_store.ts "{
  \"task_type\": \"bug-report\",
  \"pattern\": {
    \"bugKey\": \"{createdBugKey}\",
    \"repo\": \"{repository}\",
    \"severity\": \"{severity}\",
    \"isPipelineBug\": ${isPipelineMode},
    \"failingTests\": [{\"repo\": \"{repo}\", \"branch\": \"{BUG-KEY}-failing-tests\", \"testFile\": \"{path}\"}],
    \"regressionLink\": \"{original-key or null}\",
    \"outcome\": \"success\"
  }
}"
```

---

## Phase 7: Process Cleanup (MANDATORY)

**Clean up any orphaned processes spawned during bug investigation:**

```bash
/reclaim
```

This prevents zombie Chrome/Playwright Docker containers and other orphaned processes from accumulating between bug reporting runs.

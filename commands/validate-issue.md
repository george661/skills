<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Validate a single Jira issue for completeness, proper structure, and readiness
arguments:
  - name: issue_key
    description: The Jira issue key to validate (e.g., PROJECT-123)
    required: true
---

> Tool examples: [get_issue](.claude/skills/examples/jira/get_issue.md), [update_issue](.claude/skills/examples/jira/update_issue.md), [add_comment](.claude/skills/examples/jira/add_comment.md)

# Issue Validation: $ARGUMENTS.issue_key

## Overview

This command validates that a Jira issue meets quality standards for:
1. **Required Fields** - Summary, description, type, priority
2. **Proper Structure** - Acceptance criteria, technical context
3. **Repository Labels** - Correct `repo-*` labels
4. **PRP Reference** - Link to PRP document if applicable
5. **Actionability** - Clear enough to start work

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

1. Phase 1: Fetch issue details from Jira
2. Phase 2: Validate required fields
3. Phase 3: Validate description structure
4. Phase 4: Validate labels and metadata
5. Phase 5: Generate validation report
6. Phase 6: Fix issues if any found

**START NOW: Begin Phase 0/Step 0.**

---

## Phase 1: Fetch Issue Details

Print: `[phase 1/6] Fetching issue details from Jira...`

```bash
ISSUE_DATA=$(npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue_key", "fields": ["summary", "description", "issuetype", "priority", "labels", "status", "assignee", "parent", "issuelinks"]}')
echo "$ISSUE_DATA"
```

Extract and store the following fields from the response:
- `summary` — from `fields.summary`
- `description` — from `fields.description` (may be Atlassian Document Format or plain string)
- `issue_type` — from `fields.issuetype.name`
- `priority` — from `fields.priority.name`
- `labels` — from `fields.labels` (array of strings)
- `status` — from `fields.status.name`
- `parent` — from `fields.parent` (may be null)
- `issuelinks` — from `fields.issuelinks` (array)

If the API call fails or returns an error, print `[ERROR] Could not fetch issue $ARGUMENTS.issue_key` and stop.

---

## Phase 2: Validate Required Fields

Print: `[phase 2/6] Validating required fields...`

Check each condition and record PASS or FAIL:

| Check | Condition | Result variable |
|-------|-----------|-----------------|
| Summary present | `summary` is non-empty string | `check_summary` |
| Summary length | `summary` length < 255 chars | `check_summary_len` |
| Description present | `description` is non-empty (not null, not empty string, not empty ADF doc) | `check_description` |
| Issue type valid | `issue_type` is one of: Story, Bug, Task, Sub-task, Epic | `check_issuetype` |
| Priority set | `priority` is not null/undefined/"None" | `check_priority` |
| Repo label present | at least one label matches pattern `repo-*` | `check_repo_label` |

Combine `check_summary` and `check_summary_len` into a single `summary` result: PASS only if both pass.

---

## Phase 3: Validate Description Structure

Print: `[phase 3/6] Validating description structure...`

Extract the plain text of the description. If the description is Atlassian Document Format (ADF), walk the `content` array and concatenate all `text` node values to produce a plain-text representation.

Check each condition:

| Check | Condition | Result variable |
|-------|-----------|-----------------|
| Acceptance Criteria | plain text contains "Acceptance Criteria" or "acceptance criteria" (case-insensitive) | `check_ac` |
| Technical Context | plain text contains "Technical Context", "Background", or "Context" (case-insensitive) | `check_context` |
| Actionability | plain text length >= 100 characters | `check_actionable` |

---

## Phase 4: Validate Labels and Metadata

Print: `[phase 4/6] Validating labels and metadata...`

Known valid repo labels:
```
repo-frontend-app
repo-lambda-functions
repo-auth-service
repo-sdk
repo-core-infra
repo-e2e-tests
repo-project-docs
repo-agents
repo-go-common
```

Checks:

| Check | Condition | Result variable |
|-------|-----------|-----------------|
| Valid repo label | at least one label from the `labels` array is in the known list above | `check_valid_repo_label` |
| Epic parent (Stories only) | if `issue_type` == "Story": `parent` field is non-null, OR `issuelinks` contains a link with `type.name` == "Epic-Story" in the inward direction. If `issue_type` != "Story": mark N/A (counts as PASS) | `check_epic_parent` |

Additionally:
- If `status` == "Done", print a warning line: `[WARN] Issue is already Done — validation is advisory only.`
- If `issue_type` == "Epic", skip the epic parent check (`check_epic_parent` = PASS/N/A).

---

## Phase 5: Generate Validation Report

Print: `[phase 5/6] Generating validation report...`

Tally results. Count total checks (exclude N/A items from denominator). Count failures.

Print the following report to stdout:

```
=== Issue Validation: $ARGUMENTS.issue_key ===
Summary: {summary}

REQUIRED FIELDS:
  {pass/fail} Summary
  {pass/fail} Description
  {pass/fail} Issue Type: {issue_type}
  {pass/fail} Priority: {priority}
  {pass/fail} Repo Label: {comma-separated matching repo labels, or "(none)"}

DESCRIPTION STRUCTURE:
  {pass/fail} Acceptance Criteria section
  {pass/fail} Technical Context section
  {pass/fail} Actionable (>= 100 chars)

METADATA:
  {pass/fail} Valid repo label
  {pass/fail} Epic parent link (if Story) {or "N/A" if not a Story/Epic}

VERDICT: PASS ({passed_count}/{total_count} checks) | FAIL ({failed_count}/{total_count} checks failed)
```

Use `✅` for PASS and `❌` for FAIL throughout the report.

---

## Phase 6: Fix Issues If Any Found

Print: `[phase 6/6] Applying fixes for failed checks...`

For each failed check, apply the corresponding fix:

**Missing Acceptance Criteria** (`check_ac` == FAIL):
```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.issue_key", "body": "⚠️ Validation failed: Missing Acceptance Criteria section.\n\nPlease add a section like:\n## Acceptance Criteria\n- [ ] ...\n- [ ] ..."}'
```

**Missing description** (`check_description` == FAIL):
```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.issue_key", "body": "⚠️ Validation failed: Description is empty. Please fill in the issue description with context, background, and acceptance criteria before beginning work."}'
```

**Missing repo label** (`check_valid_repo_label` == FAIL):

Attempt to infer the correct repo from the description text by scanning for known repo name fragments (e.g., "frontend-app", "lambda-functions", "auth-service", "sdk", "core-infra", "e2e-tests", "project-docs", "agents", "go-common"). Only apply if exactly one match is found — do not guess when multiple repos are mentioned.

If a single repo can be inferred, merge it with existing labels and update:
```bash
npx tsx ~/.claude/skills/issues/update_issue.ts '{"issue_key": "$ARGUMENTS.issue_key", "labels": ["{existing_label_1}", "{existing_label_2}", "repo-{inferred_repo}"]}'
```

If the repo cannot be inferred, add a comment instead:
```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.issue_key", "body": "⚠️ Validation failed: No valid repo-* label found. Please add one of: repo-frontend-app, repo-lambda-functions, repo-auth-service, repo-sdk, repo-core-infra, repo-e2e-tests, repo-project-docs, repo-agents, repo-go-common"}'
```

**Store result in AgentDB** (always, regardless of PASS/FAIL):
```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{"session_id": "${TENANT_NAMESPACE}", "task": "validate-issue:$ARGUMENTS.issue_key", "reward": {0.9 if PASS else 0.5}, "success": {true if PASS else false}}'
```

Print final line:

```
[DONE] Validation complete for $ARGUMENTS.issue_key — {PASS|FAIL}
```

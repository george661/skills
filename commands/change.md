<!-- MODEL_TIER: sonnet -->
<!-- DISPATCH: Spawn a Task subagent with model: "sonnet" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Sonnet. -->

---
description: Request a change across codebases - explores repos, detects bugs vs features, avoids duplicates, creates per-repo Jira issues
arguments:
  - name: description
    description: Plain English description of the desired change (e.g., "Change the Provider TOS Acceptance page so that the form is side by side with the agreement text")
    required: true
---

> Tool examples: [search_issues](.claude/skills/examples/jira/search_issues.md), [create_issue](.claude/skills/examples/jira/create_issue.md), [add_comment](.claude/skills/examples/jira/add_comment.md), [list_transitions](.claude/skills/examples/jira/list_transitions.md), [transition_issue](.claude/skills/examples/jira/transition_issue.md)

# Change Request: $ARGUMENTS.description

## Overview

This command systematically processes a change request by:
1. Using brainstorming to refine and understand the request
2. Exploring all relevant codebases to determine scope and affected files
3. Searching Jira for duplicate or related issues
4. Detecting if this is actually a bug (and switching to /bug if so)
5. Creating separate Jira issues for each affected repository
6. Transitioning all issues to To Do status

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

1. Phase 0: Load memory, search for related context
2. Phase 1: Brainstorm and refine the change request
3. Phase 2: Explore codebases to determine scope
4. Phase 3: Search Jira for duplicates and related issues
5. Phase 4: Classify request - bug vs feature/change
5.5. Phase 4.5: Duplicate Detection Gate
6. Phase 5: Create Jira issues per affected repository
7. Phase 6: Transition all issues to To Do
8. Phase 6.5: Validate all created issues
9. Phase 6.7: Consolidation Check (creation-time hint)
10. Phase 7: Store results and output summary

**START NOW: Begin Phase 0/Step 0.**

---

## Phase 0: Load Memory and Search Context

**[phase 0/7] Loading memory and context...**

Retrieve relevant prior patterns and episodes before doing any work:

```bash
npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts '{"task": "$ARGUMENTS.description", "k": 5}'
npx tsx ~/.claude/skills/agentdb/pattern_search.ts '{"task": "$ARGUMENTS.description", "k": 5}'
```

Review the returned episodes and patterns. Note any prior work on similar changes, known affected repos, or cautionary patterns.

Print: `[phase 0/7] Context loaded.`

---

## Phase 1: Brainstorm and Refine the Change Request

**[phase 1/7] Brainstorming and refining the change...**

Apply the `/superpowers:brainstorming` mental model to the raw change description. Work through the following questions internally:

1. What is the user trying to accomplish? (underlying goal, not just the literal request)
2. What repos/systems are likely affected? (frontend, backend, SDK, tests, docs, infra)
3. Are there any ambiguities to resolve? (missing context, unclear scope, competing interpretations)
4. Is this likely a feature or enhancement — or does the description reveal a defect/regression?

Produce:
- A refined 2-3 sentence description of the change that captures intent and scope
- A list of likely affected repositories with rationale

Print: `[phase 1/7] Refined change: {refined_description}`

---

## Phase 2: Explore Codebases to Determine Scope

**[phase 2/7] Exploring codebases...**

For each likely affected repository identified in Phase 1, search for relevant code:

```bash
npx tsx ~/.claude/skills/agentdb/pattern_search.ts '{"task": "{relevant_keywords}", "k": 3}'
```

Use CodeGraphContext if available:
```
mcp__CodeGraphContext__find_code with query: {relevant_keywords}
```

For each repository, determine:
- Affected files/modules (entry points, shared utilities, types, tests)
- Rough complexity: `trivial` (1-2 files, clear change), `moderate` (3-5 files or cross-module), `complex` (architectural or cross-repo coordination required)

Print: `[phase 2/7] Scope: {repo1} ({complexity}), {repo2} ({complexity}), ...`

---

## Phase 3: Search Jira for Duplicates and Related Issues

**[phase 3/7] Searching Jira for duplicates and related issues...**

Extract 2-3 keywords from the refined change description and run:

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${PROJECT_KEY} AND summary ~ \"{keyword1}\" AND status != Done", "fields": ["key", "summary", "status", "priority", "assignee"], "max_results": 10}'
```

Run a second query for the second keyword if the first returns 0 results:

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${PROJECT_KEY} AND summary ~ \"{keyword2}\" AND status != Done", "fields": ["key", "summary", "status", "priority", "assignee"], "max_results": 10}'
```

Classify each result as one of:
- `potential_duplicate` — same intent, same target area
- `related` — overlapping scope but different goal
- `unrelated` — incidental keyword match only

Print: `[phase 3/7] Found {N} potential duplicates, {M} related issues`

---

## Phase 4.5: Duplicate Detection Gate (MANDATORY)

**[phase 4.5] Checking for duplicate change requests...**

Before creating Jira issues, search for existing issues that match:

### Step 1: Search Jira for Similar Issues

Extract 2-3 key terms from the change description and search:

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${TENANT_PROJECT} AND summary ~ "keyword1" AND summary ~ "keyword2" AND status != Done", "fields": ["key", "summary", "status", "priority"], "max_results": 10}'
```

### Step 2: Search AgentDB for Similar Patterns

```bash
npx tsx ~/.claude/skills/agentdb/pattern_search.ts '{"task": "{change_summary}", "k": 5}'
```

### Step 3: Evaluate Matches

If matches are found with similarity > 0.7 (based on summary overlap, same repo, same scope):

1. Present matches to user:
   ```
   Potential duplicates found:
     - {key}: {summary} (status: {status})
     - {key}: {summary} (status: {status})
   Is this a duplicate of any of these? [Y/N]
   ```

2. If user confirms duplicate (Y):
   - Link to the existing issue instead of creating new ones
   - Add a comment on the existing issue noting the change request
   - STOP -- do not create new issues

3. If user says not a duplicate (N):
   - Store the relationship in AgentDB to avoid re-flagging:
     ```bash
     npx tsx ~/.claude/skills/agentdb/pattern_store.ts '{"task_type": "dedup-declined", "approach": "{new_summary} vs {existing_key}", "success_rate": 0}'
     ```
   - Proceed with issue creation

4. If no matches found: proceed with issue creation.
---

## Phase 6.7: Consolidation Check (Creation-Time Hint)

**[phase 6.7/7] Checking for consolidation opportunities...**

After all issues are created, check the garden cache for open issues that overlap in scope
with any of the newly created issues:

```bash
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
    # referenced in the new issues' descriptions
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
3. If no cache present or no candidates found: skip silently

---

## Phase 5: Create Jira Issues Per Affected Repository

**[phase 5/7] Creating Jira issues...**

For each affected repository determined in Phase 2 (that passed the duplicate gate in Phase 4.5), create a Jira issue:

```bash
npx tsx ~/.claude/skills/issues/create_issue.ts '{
  "project": "${PROJECT_KEY}",
  "summary": "[{repo}] {refined_description}",
  "description": "{full_context_with_affected_files}",
  "issue_type": "Story",
  "priority": "Medium",
  "labels": ["step:backlog"]
}'
```

The `description` field should include:
- The refined change description from Phase 1
- Affected files/modules identified in Phase 2
- Complexity rating
- Any related issue keys from Phase 3

Collect all created issue keys for use in subsequent phases.

---

## Phase 6: Transition All Issues to To Do

**[phase 6/7] Transitioning issues to To Do...**

For each created issue key from Phase 5:

```bash
TRANSITIONS=$(npx tsx ~/.claude/skills/issues/list_transitions.ts '{"issue_key": "{key}"}')
TODO_ID=$(echo "$TRANSITIONS" | python3 -c "import json,sys; t=json.load(sys.stdin); print(next(x['id'] for x in t if 'do' in x['name'].lower()))")
npx tsx ~/.claude/skills/issues/transition_issue.ts '{"issue_key": "{key}", "transition_id": "'"$TODO_ID"'"}'
```

---

## Phase 7: Store Results and Output Summary

**[phase 7/7] Storing results and printing summary...**

Store the episode in AgentDB:

```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{"session_id": "${TENANT_NAMESPACE}", "task": "change:$ARGUMENTS.description", "reward": 0.9, "success": true}'
```

Print the final summary:

```
Change Request: {refined_description}

Created Issues:
| Repo | Issue | Summary | Status |
|------|-------|---------|--------|
| {repo} | {key} | {summary} | To Do |

Related Issues: {related_keys}
Next step: Run /work {first_issue_key}
```

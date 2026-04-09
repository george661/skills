<!-- MODEL_TIER: sonnet -->
<!-- DISPATCH: Spawn a Task subagent with model: "sonnet" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Sonnet. -->

---
description: Create a Jira issue with PRP from text description - uses brainstorming to refine, determines issue type, creates appropriate Jira issue
arguments:
  - name: description
    description: Brief description of the issue or feature request
    required: true
---

> Tool examples: [search_issues](.claude/skills/examples/jira/search_issues.md), [create_issue](.claude/skills/examples/jira/create_issue.md), [add_comment](.claude/skills/examples/jira/add_comment.md), [list_transitions](.claude/skills/examples/jira/list_transitions.md), [transition_issue](.claude/skills/examples/jira/transition_issue.md)

# Issue Creation Workflow: $ARGUMENTS.description

## Overview

This command systematically creates a Jira issue by:
1. Using superpowers brainstorming to refine the user's ask
2. Creating a PRP (Problem Requirements Plan) in project-docs
3. Determining if the issue is an Epic, Epic-child, or standalone maintenance issue
4. Creating the appropriate Jira issue with full context

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

1. Phase 0: Load memory, search for related context
2. Phase 1: Brainstorm and refine the user's ask
3. Phase 2: Create PRP document in project-docs
4. Phase 3: Determine issue type (Epic/Child/Standalone)
4.5. Phase 3.5: Duplicate Detection Gate
5. Phase 4: Create Jira issue with appropriate type
6. Phase 5: Link PRP to Jira, transition to To Do
7. Phase 5.5: Validate created issue
8. Phase 5.7: Consolidation Check (creation-time hint)
9. Phase 6: Store results in memory, provide summary

**START NOW: Begin Phase 0/Step 0.**

---

---

## Phase 3.5: Duplicate Detection Gate (MANDATORY)

**[phase 3.5] Checking for duplicate issues...**

Before creating the Jira issue, search for existing issues that match:

### Step 1: Search Jira for Similar Issues

Extract 2-3 key terms from the issue summary and search:

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${TENANT_PROJECT} AND summary ~ "keyword1" AND summary ~ "keyword2" AND status != Done", "fields": ["key", "summary", "status", "priority"], "max_results": 10}'
```

### Step 2: Search AgentDB for Similar Patterns

```bash
npx tsx ~/.claude/skills/agentdb/pattern_search.ts '{"task": "{issue_summary}", "k": 5}'
```

### Step 3: Evaluate Matches

If matches are found with similarity > 0.7 (based on summary overlap, same repo, same domain):

1. Present matches to user:
   ```
   Potential duplicates found:
     - {key}: {summary} (status: {status})
     - {key}: {summary} (status: {status})
   Is this a duplicate of any of these? [Y/N]
   ```

2. If user confirms duplicate (Y):
   - Link to the existing issue instead of creating a new one
   - Add a comment on the existing issue noting the duplicate request
   - STOP -- do not create a new issue

3. If user says not a duplicate (N):
   - Store the relationship in AgentDB to avoid re-flagging:
     ```bash
     npx tsx ~/.claude/skills/agentdb/pattern_store.ts '{"task_type": "dedup-declined", "approach": "{new_summary} vs {existing_key}", "success_rate": 0}'
     ```
   - Proceed with issue creation

4. If no matches found: proceed with issue creation.

## Phase 5.3: E2E Spec Authoring for Observable Issues

**If `$E2E_REPO` is unset:** Skip.

Apply the same observable-effects heuristic as `/e2e-write` Step 3:
- AC mentions something a user sees, views, navigates to, clicks
- Issue description mentions UI, page, form, table, modal, dashboard
- Issue affects data rendered in the frontend

**If observable:** Call `/e2e-write $ARGUMENTS` immediately while AC is fresh in context.
The draft PR is opened in `$E2E_REPO`. When `/work` is later run, `/e2e-verify-red`
confirms the spec correctly fails before any code is written.

**If not observable:** No action. `e2e.not-applicable` will be set by `/e2e-write` if called later.

---

## Phase 5.7: Consolidation Check (Creation-Time Hint)

**[phase 5.7/6] Checking for consolidation opportunities...**

After issue creation, check the garden cache for open issues that overlap in scope:

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
    # referenced in the new issue's description
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

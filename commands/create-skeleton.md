<!-- MODEL_TIER: opus -->
<!-- DISPATCH: Spawn a Task subagent with model: "opus" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Opus. -->

---
description: Create a walking skeleton definition for an epic - identifies minimal end-to-end path across repos, creates skeleton Jira issues, and links dependencies
arguments:
  - name: epic
    description: Jira Epic key (e.g., PROJ-123)
    required: true
---

> Tool examples: [get_issue](.claude/skills/examples/jira/get_issue.md), [search_issues](.claude/skills/examples/jira/search_issues.md), [create_issue](.claude/skills/examples/jira/create_issue.md), [update_issue](.claude/skills/examples/jira/update_issue.md), [add_comment](.claude/skills/examples/jira/add_comment.md)

# Create Walking Skeleton: $ARGUMENTS.epic

## Overview

A walking skeleton is the thinnest possible vertical slice that proves the architecture works
end-to-end. This command analyzes an epic's PRP content, identifies every affected repository,
defines the minimal path through each layer (frontend routes, API endpoints, DB schemas,
shared types), creates dedicated skeleton Jira issues, and links all non-skeleton issues as
blocked by the skeleton.

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/7] Defining skeleton path...`).

1. Phase 0: Load Epic Context
2. Phase 1: Identify Affected Repos
3. Phase 2: Define Skeleton Path
4. Phase 3: Define E2E Tests
5. Phase 4: Create Skeleton Jira Issues
6. Phase 5: Create Dependency Links
7. Phase 6: Store Definition
8. Phase 7: Output Summary

**START NOW: Begin Phase 0.**

---

## Phase 0: Load Epic Context

**[phase 0/7] Loading epic context...**

1. Fetch the epic from Jira:
   ```bash
   npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.epic", "fields": ["summary", "description", "issuelinks", "labels", "status"]}'
   ```

2. Fetch all child issues:
   ```bash
   npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "parent = $ARGUMENTS.epic", "fields": ["key", "summary", "description", "status", "labels"]}'
   ```

3. Read PRP if it exists (check AgentDB for planned epic data):
   ```bash
   npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "planned-$ARGUMENTS.epic", "k": 1}'
   ```

4. Also search for the PRP file in the docs repo:
   ```bash
   grep -rl "$ARGUMENTS.epic" ${PROJECT_ROOT}/${DOCS_REPO}/PRPs/ 2>/dev/null | head -3
   ```
   If found, read the PRP file to extract implementation tasks, affected repos, and acceptance criteria.

Store as `EPIC_SUMMARY`, `EPIC_DESCRIPTION`, `CHILD_ISSUES[]`, `PRP_CONTENT`.

---

## Phase 1: Identify Affected Repos

**[phase 1/7] Identifying affected repositories...**

1. From the epic description, child issue descriptions, and PRP content, extract all repository references.
   Look for patterns: `project-*` repo names, `repo-*` labels, explicit repository mentions.

2. If CGC is available, search for key domain terms from the epic:
   ```
   mcp__CodeGraphContext__find_code with query terms from epic summary
   ```

3. Build `AFFECTED_REPOS[]` -- the list of all repositories that will be touched by this epic.

4. For each repo, classify its role in the skeleton:
   - **Frontend**: frontend-app, dashboard (routes, pages, components)
   - **API/Lambda**: lambda-functions, api-service (endpoints, handlers)
   - **Shared libraries**: go-common (types, models, services)
   - **Database/Infra**: core-infra, migrations (tables, schemas)
   - **Auth**: auth-service (auth flows, token generation)
   - **E2E Testing**: e2e-tests (journey tests, page objects)
   - **SDK**: sdk (publisher-facing types)

---

## Phase 2: Define Skeleton Path

**[phase 2/7] Defining minimal end-to-end path...**

For each affected repo, identify the MINIMAL set of changes that prove the architecture works.
The skeleton is NOT the full implementation -- it is the thinnest vertical slice.

### Frontend (frontend-app / dashboard)
- Route definition (even if page is a stub)
- Navigation entry (menu item or link)
- Minimal page component that renders and calls the API

### API/Lambda (lambda-functions)
- Lambda handler with request parsing and response structure
- API Gateway route in OpenAPI spec
- Minimal business logic (can return hardcoded/minimal data)

### Shared Types (go-common)
- Model structs with JSON tags
- Request/response DTOs

### Database (core-infra / migrations)
- DynamoDB table definition in Terraform
- Migration script if needed

### Auth (auth-service)
- Token claims or permission changes

### E2E (e2e-tests)
- Journey test that exercises the skeleton path end-to-end

Build `SKELETON_PATH` -- a structured definition:

```
SKELETON_PATH:
  {repo_name}:
    files_to_create: [list of new files]
    files_to_modify: [list of existing files]
    minimal_scope: "description of what the skeleton includes in this repo"
    proves: "what architectural assumption this validates"
```

---

## Phase 3: Define E2E Tests

**[phase 3/7] Defining E2E test coverage for skeleton...**

For the skeleton path, define Playwright journey tests that exercise it end-to-end:

1. **Test file**: `e2e-tests/tests/journeys/{domain}.spec.ts`
   - Determine the domain from the epic's primary feature area
   - If an existing journey file covers this domain, note modifications needed
   - If new, define the journey file name

2. **Page objects needed**: `e2e-tests/pages/{PageName}.ts`
   - List new page objects for skeleton UI components
   - List modifications to existing page objects

3. **Test data requirements**:
   - What test fixtures are needed
   - What user roles are required (from test-data)

4. **Skeleton test scope**:
   - Happy path only (no edge cases in skeleton)
   - Verify navigation works
   - Verify API call succeeds
   - Verify data renders on page

Store as `SKELETON_E2E_PLAN`.

---

## Phase 4: Create Skeleton Jira Issues

**[phase 4/7] Creating skeleton issues in Jira...**

For each repo in the skeleton path, create a dedicated Jira issue:

```bash
npx tsx ~/.claude/skills/issues/create_issue.ts '{
  "project_key": "${TENANT_PROJECT}",
  "summary": "[Skeleton] ${EPIC_SUMMARY} - {repo_name}",
  "issue_type": "Task",
  "parent_key": "$ARGUMENTS.epic",
  "labels": ["skeleton", "repo-{repo_name}"],
  "description": "## Walking Skeleton Task\n\n**Epic:** $ARGUMENTS.epic\n**Repository:** {repo_name}\n**Skeleton scope:**\n\n{minimal_scope from SKELETON_PATH}\n\n**Files to create:**\n{files_to_create}\n\n**Files to modify:**\n{files_to_modify}\n\n**Proves:** {architectural_assumption}\n\n**Acceptance Criteria:**\n- [ ] Minimal implementation compiles and deploys\n- [ ] End-to-end path exercisable (even with stub data)\n- [ ] E2E test passes for skeleton path\n- [ ] No dead code or orphaned imports\n\n**E2E Test Requirements:**\n{SKELETON_E2E_PLAN excerpt for this repo}"
}'
```

Store created issue keys in `SKELETON_ISSUES[]`.

If an E2E skeleton issue is warranted (e2e-tests is in affected repos):

```bash
npx tsx ~/.claude/skills/issues/create_issue.ts '{
  "project_key": "${TENANT_PROJECT}",
  "summary": "[Skeleton] ${EPIC_SUMMARY} - e2e-tests journey tests",
  "issue_type": "Task",
  "parent_key": "$ARGUMENTS.epic",
  "labels": ["skeleton", "repo-e2e-tests", "test-task"],
  "description": "## Walking Skeleton E2E Tests\n\n**Epic:** $ARGUMENTS.epic\n\n**Journey test:** {test_file}\n**Page objects:** {page_objects}\n**Test data:** {fixtures}\n\n**Acceptance Criteria:**\n- [ ] Journey test exercises skeleton end-to-end\n- [ ] Happy path passes\n- [ ] Page objects created for new UI components"
}'
```

---

## Phase 5: Create Dependency Links

**[phase 5/7] Linking non-skeleton issues as blocked by skeleton...**

For each existing child issue of the epic that is NOT a skeleton issue:

1. Check if the child issue has the `skeleton` label. If yes, skip.
2. Determine which skeleton issue(s) it depends on (by repository overlap).
3. Create `is_blocked_by` links:

```bash
# For each non-skeleton child issue, link to relevant skeleton issue(s)
npx tsx ~/.claude/skills/issues/update_issue.ts '{
  "issue_key": "{child_key}",
  "fields": {
    "issuelinks": [{"type": {"name": "Blocks"}, "inwardIssue": {"key": "{skeleton_key}"}}]
  }
}'
```

Print summary of links created.

---

## Phase 6: Store Definition

**[phase 6/7] Storing skeleton definition...**

1. Write the skeleton definition document:
   ```bash
   mkdir -p ${DESIGN_DOCS_PATH}/skeletons/
   ```

   Create `${DESIGN_DOCS_PATH}/skeletons/$ARGUMENTS.epic-skeleton.md` containing:
   - Epic summary and key
   - Affected repos with skeleton scope per repo
   - Skeleton path definition
   - E2E test plan
   - Created Jira issue keys
   - Dependency link summary

2. Store in AgentDB:
   ```bash
   npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{
     "session_id": "${TENANT_NAMESPACE}",
     "task": "skeleton-$ARGUMENTS.epic",
     "reward": 1.0,
     "success": true,
     "metadata": {
       "epic": "$ARGUMENTS.epic",
       "repos": ["list of affected repos"],
       "skeleton_issues": ["list of skeleton issue keys"],
       "e2e_plan": "summary of e2e test plan"
     }
   }'
   ```

---

## Phase 7: Output Summary

**[phase 7/7] Skeleton definition complete.**

```
## Walking Skeleton: $ARGUMENTS.epic

**Epic:** {EPIC_SUMMARY}

**Affected Repositories:** {count}
  - {repo list}

**Skeleton Issues Created:** {count}
  - {key}: {summary} (per issue)

**Dependency Links:** {count} non-skeleton issues linked as blocked-by skeleton

**E2E Test Plan:**
  - Journey: {test_file}
  - Page Objects: {count}
  - Fixtures: {list}

**Skeleton Document:** ${DESIGN_DOCS_PATH}/skeletons/$ARGUMENTS.epic-skeleton.md

**Next Steps:**
1. Run /review-skeleton $ARGUMENTS.epic to validate coverage
2. If approved, skeleton issues are ready for /work
```

---

## Anti-Patterns

| Don't | Do Instead |
|---|---|
| Include full feature implementation in skeleton | Define thinnest possible vertical slice |
| Skip E2E test definition | Every skeleton must have an E2E test plan |
| Create skeleton without PRP | Read PRP first to understand full scope |
| Put all skeleton work in one issue | Create per-repo skeleton issues |
| Skip dependency links | Non-skeleton issues must be blocked by skeleton |
| Define skeleton for single layer only | Skeleton must span the full stack relevant to the epic |

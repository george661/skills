<!-- MODEL_TIER: sonnet -->
<!-- DISPATCH: Spawn a Task subagent with model: "sonnet" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Sonnet. -->

---
description: Consolidate open PRs in a Bitbucket repository into a single PR
arguments:
  - name: repo
    description: Repository slug (e.g., frontend-app, api-service, auth-service)
    required: true
---

# Consolidate PRs: $ARGUMENTS.repo

## Purpose

This command consolidates multiple open PRs in a repository into a single consolidated PR:
- Lists all open PRs and their details
- Shows preview for user confirmation before proceeding
- Merges all feature branches into a consolidated branch
- Runs validation (lint, typecheck, tests)
- Creates a new consolidated PR
- Declines old PRs with reference to the new one
- Updates related Jira issues

**Usage:** `/consolidate-prs frontend-app`

---

## GUARDRAILS - Safety Checks

### Pre-Consolidation Checks

1. **Minimum PR Count**: Only consolidate if there are 2+ open PRs
2. **No Conflicting Changes**: Abort if branches have merge conflicts
3. **User Confirmation**: ALWAYS show preview and wait for explicit approval before:
   - Declining any PRs
   - Creating the consolidated PR
4. **Test Validation**: All tests must pass before creating consolidated PR
5. **Branch Safety**: Never force-push or modify main/develop branches

### Repositories Allowed

Only consolidate PRs for known project repositories:
- `frontend-app` - Frontend application
- `api-service` - Core API
- `auth-service` - Authentication service
- `sdk` - Publisher SDK
- `project-docs` - Documentation (PRs only, no code tests)
- `test-data` - Test fixtures

---

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

1. Validate repository slug
2. List and analyze open PRs
3. Show preview and get user confirmation
4. Create consolidated feature branch
5. Merge all feature branches
6. Run validation (lint, typecheck, tests)
7. Push consolidated branch
8. Create consolidated PR
9. Decline old PRs with reference
10. Update related Jira issues

**START NOW: Begin Phase 0/Step 0.**

---

## Phase 0: Validate Repository Slug

Print: `[phase 0/10] Validating repository slug...`

Check that `$ARGUMENTS.repo` is in the allowed list:

```
ALLOWED_REPOS = [frontend-app, api-service, auth-service, sdk, project-docs, test-data]
```

If `$ARGUMENTS.repo` is NOT in the allowed list, print:

```
ERROR: "$ARGUMENTS.repo" is not in the allowed repository list.
Allowed repositories: frontend-app, api-service, auth-service, sdk, project-docs, test-data
```

Then stop — do not proceed to Phase 1.

Resolve PROJECT_ROOT by reading the `.env` file from the project root. The local repository path is `$PROJECT_ROOT/$ARGUMENTS.repo`.

Confirm the local repo directory exists:

```bash
ls "$PROJECT_ROOT/$ARGUMENTS.repo" > /dev/null 2>&1
```

If the directory does not exist, print:

```
ERROR: Local repository directory not found at $PROJECT_ROOT/$ARGUMENTS.repo
Make sure the repository is cloned and PROJECT_ROOT is set correctly.
```

Then stop.

Store the repo slug in a variable `REPO` for use in all subsequent phases.

---

## Phase 1: List and Analyze Open PRs

Print: `[phase 1/10] Listing open PRs in $ARGUMENTS.repo...`

Call:

```bash
npx tsx ~/.claude/skills/bitbucket/list_pull_requests.ts '{"repo_slug": "$ARGUMENTS.repo", "state": "OPEN"}'
```

Parse the response to extract the list of open PRs. Each PR should yield:
- `id` — PR number
- `title` — PR title
- `source.branch.name` — source branch name
- `author.display_name` — PR author
- `links.self[0].href` — PR URL

If the response contains fewer than 2 open PRs, print:

```
INFO: Found N open PR(s) in $ARGUMENTS.repo. At least 2 are required to consolidate.
Nothing to do.
```

Then stop — do not proceed.

Store the list of PRs for use in subsequent phases.

---

## Phase 2: Show Preview and Get User Confirmation

Print: `[phase 2/10] Preparing consolidation preview...`

For each open PR, fetch its details to get commit count:

```bash
npx tsx ~/.claude/skills/bitbucket/get_pull_request.ts '{"repo_slug": "$ARGUMENTS.repo", "pull_request_id": <id>}'
```

Display a formatted table of all open PRs:

```
Consolidation Preview — $ARGUMENTS.repo
========================================

  #   | Title                          | Source Branch              | Author          | Commits
------|--------------------------------|----------------------------|-----------------|--------
  42  | feat: add user dashboard       | feature/PROJ-100-user-dash   | Jane Smith      | 3
  47  | fix: token validation error    | fix/PROJ-120-token-fix       | John Doe        | 1
  51  | chore: update dependencies     | chore/PROJ-131-dep-update    | Jane Smith      | 2

Total: 3 PRs will be merged into a single consolidated branch.

Actions that will be taken:
  1. Create consolidated branch: consolidated/YYYYMMDD-all-features
  2. Merge all 3 source branches into the consolidated branch
  3. Run lint, typecheck, and tests
  4. Create 1 new consolidated PR targeting main/develop
  5. Decline 3 existing PRs with a reference to the new PR

Proceed? [Y/N]:
```

Wait for explicit user input.

- If the user types `Y` or `y` — continue to Phase 3.
- If the user types anything else — print `Consolidation cancelled.` and stop.

---

## Phase 3: Create Consolidated Feature Branch

Print: `[phase 3/10] Creating consolidated branch...`

Determine the base branch by inspecting the destination branch of the first open PR (typically `main` or `develop`).

Generate the consolidated branch name using today's date:

```bash
CONSOLIDATED_BRANCH="consolidated/$(date +%Y%m%d)-all-features"
```

Create the branch via Bitbucket:

```bash
npx tsx ~/.claude/skills/bitbucket/create_branch.ts '{
  "repo_slug": "$ARGUMENTS.repo",
  "branch_name": "'"$CONSOLIDATED_BRANCH"'",
  "source_branch": "<base_branch>"
}'
```

If the branch creation fails (e.g., already exists), print the error and stop.

Print: `Created branch: $CONSOLIDATED_BRANCH`

Store `CONSOLIDATED_BRANCH` for use in subsequent phases.

---

## Phase 4: Merge All Feature Branches

Print: `[phase 4/10] Merging feature branches into $CONSOLIDATED_BRANCH...`

Run the following sequence in the local repository. For each PR's source branch (in order of PR number ascending):

```bash
cd "$PROJECT_ROOT/$ARGUMENTS.repo"
git fetch origin
git checkout "$CONSOLIDATED_BRANCH"
git merge "origin/<source_branch>" --no-ff -m "Merge branch '<source_branch>' into $CONSOLIDATED_BRANCH"
```

If any `git merge` exits with a non-zero status code, a conflict has occurred. Print:

```
ERROR: Merge conflict merging <source_branch> into $CONSOLIDATED_BRANCH.
Resolve conflicts manually, then re-run /consolidate-prs $ARGUMENTS.repo.
```

Run `git merge --abort` to clean up, then stop.

After each successful merge, print: `  Merged: <source_branch>`

After all branches are merged, print: `All branches merged successfully.`

---

## Phase 5: Run Validation

Print: `[phase 5/10] Running validation...`

Detect the repository type by checking for `package.json` vs `go.mod` in `$PROJECT_ROOT/$ARGUMENTS.repo`:

```bash
if [ -f "$PROJECT_ROOT/$ARGUMENTS.repo/package.json" ]; then
  REPO_TYPE="typescript"
elif [ -f "$PROJECT_ROOT/$ARGUMENTS.repo/go.mod" ]; then
  REPO_TYPE="go"
else
  REPO_TYPE="unknown"
fi
```

**TypeScript repositories** (`package.json` present):

```bash
cd "$PROJECT_ROOT/$ARGUMENTS.repo"
npm run lint && npm run typecheck && npm run test
```

**Go repositories** (`go.mod` present):

```bash
cd "$PROJECT_ROOT/$ARGUMENTS.repo"
go vet ./... && go test ./...
```

**Unknown type** — `project-docs` and similar documentation-only repos skip code tests:

```bash
echo "Documentation-only repository. Skipping code tests."
```

If any validation command fails (non-zero exit), print:

```
ERROR: Validation failed in phase 5. Fix errors before consolidating.
Output:
<captured stderr/stdout>
```

Then stop — do not create the consolidated PR.

After all checks pass, print: `Validation passed.`

---

## Phase 6: Push Consolidated Branch

Print: `[phase 6/10] Pushing consolidated branch to origin...`

```bash
cd "$PROJECT_ROOT/$ARGUMENTS.repo"
git push origin "$CONSOLIDATED_BRANCH"
```

If push fails, print the error and stop.

Print: `Pushed $CONSOLIDATED_BRANCH to origin.`

---

## Phase 7: Create Consolidated PR

Print: `[phase 7/10] Creating consolidated PR...`

Build a description that lists all merged PRs. Format:

```
This consolidated PR merges the following open PRs:

- PR #42: feat: add user dashboard (feature/PROJ-100-user-dash)
- PR #47: fix: token validation error (fix/PROJ-120-token-fix)
- PR #51: chore: update dependencies (chore/PROJ-131-dep-update)

Original PRs have been declined with a reference to this PR.
```

Call:

```bash
npx tsx ~/.claude/skills/bitbucket/create_pull_request.ts '{
  "repo_slug": "$ARGUMENTS.repo",
  "title": "chore: consolidated PR (<count> features)",
  "source_branch": "'"$CONSOLIDATED_BRANCH"'",
  "destination_branch": "<base_branch>",
  "description": "<description above>"
}'
```

Parse the response to capture the new PR's `id` and `links.self[0].href`.

Print:

```
Created consolidated PR #<new_id>: <new_pr_url>
```

Store `NEW_PR_ID` and `NEW_PR_URL` for use in subsequent phases.

---

## Phase 8: Decline Old PRs

Print: `[phase 8/10] Declining old PRs with reference to consolidated PR...`

For each original open PR (from Phase 1), call:

```bash
npx tsx ~/.claude/skills/bitbucket/decline_pull_request.ts '{
  "repo_slug": "$ARGUMENTS.repo",
  "pull_request_id": <id>,
  "message": "This PR has been superseded by consolidated PR #<NEW_PR_ID>: <NEW_PR_URL>"
}'
```

After each successful decline, print: `  Declined PR #<id>: <title>`

If any decline call fails, print a warning but continue to the next PR — do not abort the phase.

---

## Phase 9: Update Jira Issues and Store Episode

Print: `[phase 9/10] Updating related Jira issues...`

For each original PR's source branch name, extract the Jira issue key using the pattern `[A-Z]+-[0-9]+` (e.g., `feature/PROJ-100-user-dash` → `PROJ-100`).

If an issue key is found in the branch name, search Jira to confirm the issue exists:

```bash
npx tsx ~/.claude/skills/issues/search_issues.ts '{
  "jql": "key = <issue_key>",
  "fields": ["key", "summary", "status"]
}'
```

If the issue exists, add a comment:

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{
  "issue_key": "<issue_key>",
  "body": "The feature branch for this issue has been consolidated into PR #<NEW_PR_ID> in $ARGUMENTS.repo: <NEW_PR_URL>\n\nOriginal PR #<original_id> has been declined."
}'
```

After processing all issues, print: `Jira issues updated.`

Store the episode in AgentDB:

```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{
  "session_id": "${TENANT_NAMESPACE}",
  "task": "consolidate-prs: merged <count> open PRs in $ARGUMENTS.repo into consolidated PR #<NEW_PR_ID>",
  "reward": 0.9,
  "success": true
}'
```

Print:

```
[phase 9/10] Complete.

Consolidation Summary
======================
Repository : $ARGUMENTS.repo
Branch     : $CONSOLIDATED_BRANCH
New PR     : #<NEW_PR_ID> — <NEW_PR_URL>
PRs merged : <count>
PRs declined: <count>
Jira issues updated: <count>
```

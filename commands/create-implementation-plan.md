<!-- MODEL_TIER: opus -->
<!-- DISPATCH: Spawn a Task subagent with model: "opus" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Opus. -->

---
description: Ingest Jira issue, check memory, create detailed implementation plan and save to card
arguments:
  - name: issue
    description: Jira issue key (e.g., PROJ-123)
    required: true
---

# Create Implementation Plan: $ARGUMENTS.issue

## MANDATORY: Worktree + PR Workflow

> **CRITICAL REQUIREMENT:** This command MUST create a git worktree based on `origin/main`.
>
> **ALL repository modifications will be BLOCKED by the `enforce-worktree.sh` hook unless:**
> 1. You are working in a git worktree (not the main repo)
> 2. The worktree branch is based on `origin/main`
>
> **The workflow enforces:**
> - All changes in worktree -> Create PR -> Review -> Merge via PR
> - NO direct pushes to main are allowed
>
> **Phase 2 of this command creates the worktree. Do not skip it.**

---

## Tool Usage Reference

> See `.claude/skills/examples/{tool}-mcp.md` for optimized tool patterns

---

## Purpose

This command handles the planning phase of issue implementation:
- Load context from memory and Jira
- Classify issue type
- **MANDATORY: Create worktree and feature branch from origin/main**
- Write detailed implementation plan with validation criteria
- **Assess test infrastructure impact (test-data, e2e-tests, Mockoon, BOM)**
- Save plan to Jira card

**Next step after this command:** Run `/implement $ARGUMENTS.issue`

---

## MANDATORY: Create Phase TodoWrite Items

**BEFORE doing anything else**, create these TodoWrite items:

```typescript
TodoWrite({
  todos: [
    { content: "Phase 0: Load memory and search for $ARGUMENTS.issue context", status: "pending", activeForm: "Loading context" },
    { content: "Phase 0.5: Load domain context", status: "pending", activeForm: "Loading domain context" },
    { content: "Phase 0.7: File discovery and feasibility scan — confirm exact file paths, verify claims are implementable", status: "pending", activeForm: "Discovering files" },
    { content: "Phase 0.8: Already-implemented gate — read key files, STOP if issue is already done", status: "pending", activeForm: "Checking if already done" },
    { content: "Phase 1: Get issue details, classify issue type, transition to In Progress", status: "pending", activeForm: "Claiming issue" },
    { content: "Phase 2: Create worktree and feature branch", status: "pending", activeForm: "Creating worktree" },
    { content: "Phase 3: Write plan WITH MANDATORY VALIDATION CRITERIA", status: "pending", activeForm: "Planning implementation" },
    { content: "Phase 3.5: Assess test infrastructure impact", status: "pending", activeForm: "Assessing test infrastructure" }
  ]
})
```

---

## Phase Gates (CANNOT PROCEED WITHOUT)

| From | To | Gate Requirement |
|------|-----|------------------|
| 0 | 0.5 | AgentDB health verified, memory loaded, agentdb memory searched |
| 0.5 | 0.7 | Domain context loaded (or skipped if not configured) |
| 0.7 | 0.8 | File discovery complete — exact file paths confirmed, feasibility assessed |
| 0.8 | 1 | Already-implemented check passed — issue is genuinely new work |
| 1 | 2 | Issue transitioned to In Progress, **ISSUE TYPE CLASSIFIED** |
| 2 | 3 | Worktree created, branch pushed to origin |
| 3 | 3.5 | Plan documented in Jira **WITH VALIDATION CRITERIA** (NO file written) |
| 3.5 | Done | Test infrastructure impact assessed and documented |

---

## Phase 0: Retrieve Relevant Patterns

**Retrieve patterns before starting implementation planning:**

```bash
# Search for implementation planning patterns
npx tsx ~/.claude/skills/agentdb/pattern_search.ts "{\"task\": \"implementation planning patterns for ${issueType}\", \"k\": 5, \"threshold\": 0.6}"

# Retrieve relevant episodes for implementation planning
npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts "{\"task\": \"create-implementation-plan ${issueKey}\", \"k\": 3}"

# Search for anti-patterns to AVOID
npx tsx ~/.claude/skills/agentdb/pattern_search.ts "{\"task\": \"anti-pattern work\", \"k\": 3, \"filters\": {\"maxSuccessRate\": 0.3}}"
```

**Surface Context — review retrieved patterns before proceeding:**

If patterns indicate known blockers for this issue type:
1. Document the blockers in the implementation plan
2. Plan mitigation strategies
3. Consider alternative approaches with higher success rates

If similar episodes show repeated failures:
1. Identify root cause from episode critiques
2. Address root cause in implementation approach
3. Add specific validation criteria to catch the failure mode

If anti-patterns match the current task:
1. Avoid the documented anti-pattern approach
2. Follow the suggested alternative
3. Add the anti-pattern to the implementation plan as a risk

**Pattern-Informed Checklist:**
- [ ] Reviewed strategy patterns for this issue type
- [ ] Checked for known blockers
- [ ] Reviewed similar past episodes
- [ ] Checked anti-patterns for this command type
- [ ] Documented any concerns in implementation plan

---

## Phase 0.5: Load Domain Context

> **Skill reference:** [domain-context](.claude/skills/domain-context.skill.md)

**Skip if `TENANT_DOMAIN_PATH` is not set or domain index does not exist.**

Identify the bounded context for this issue from:
1. `domain:{ContextName}` label on the Jira issue (set during grooming)
2. Repository name to context mapping from tenant config
3. Issue description keyword matching against context responsibilities

Load the specific bounded context details:

```bash
python3 -c "
import json, os
idx = json.load(open(os.path.join(os.environ.get('TENANT_DOMAIN_PATH',''), os.environ.get('TENANT_DOMAIN_INDEX','domain-index.json'))))
# Replace <ContextName> with the identified context
ctx_name = '<ContextName>'
ctx = idx['contexts'].get(ctx_name, {})
print(f'Context: {ctx_name}')
print(f'Aggregates: {[a[\"name\"] for a in ctx.get(\"aggregates\", [])]}')
print(f'Commands: {[c[\"name\"] for c in ctx.get(\"commands\", [])]}')
print(f'Events: {[e[\"name\"] for e in ctx.get(\"events\", [])]}')
print(f'Flows: {[f[\"name\"] for f in ctx.get(\"flows\", [])]}')
"
```

Store the bounded context details for use in the implementation plan.

---

## Phase 0.7: File Discovery and Feasibility Scan (MANDATORY)

**Before claiming the issue or creating any side effects, verify that the acceptance criteria are actually implementable and confirm exact file paths.**

This prevents two failure modes:
1. Creating worktrees/branches/Jira transitions for work that is already done
2. Writing plans with wrong file paths or unimplementable claims

### 0.7.1 Extract Testable Claims from Acceptance Criteria

Parse the Jira acceptance criteria and identify every claim about system behavior:
- "Clicking X shows Y"
- "Navigating to /path displays Z"
- "API returns error when..."
- "Status changes to revoked"

### 0.7.2 Verify Each Claim Against Source Code

For each behavioral claim, read the actual source code to confirm the behavior exists:

```bash
# For frontend claims: read the relevant page/component
# For API claims: read the handler/Lambda function
# For E2E claims: read both the frontend component AND the backend handler
# For data claims: check DynamoDB table definitions and indexes
```

**Check specifically:**
- Does the UI component render the described state/element?
- Does the API endpoint handle the described scenario?
- Do the database indexes support the described query?
- **Target directory verification:** If the plan creates or extends files in a specific directory,
  verify that directory actually contains the functionality being tested/modified. For example,
  if the Jira says "test the reconciliation API" and the plan targets `functions/payments/`,
  grep that directory for "reconciliation" — if it's not there, the target is wrong. The Jira
  description may suggest a location that is architecturally incorrect; trust the source code
  over the Jira description when they conflict.

### 0.7.3 Configuration Sanity Check (if applicable)

**For issues involving runtime errors (500s, crashes, initialization failures)**, check for
configuration mismatches before writing the plan. These are a common root cause class.

1. **Find config sources**: Identify where the service reads configuration (env vars, config files, tfvars)
2. **Find code defaults**: Find the fallback/default values in the source code
3. **Compare**: Flag any mismatch between configured values and code defaults
4. **Cross-reference infrastructure**: If the config references external resources (DB indexes,
   table names, queue names), verify the actual resource matches the configured name

This check is language/framework agnostic. The repo's CLAUDE.md may document project-specific
config patterns (e.g., "env vars are set in tfvars" or "config comes from SSM parameters").

**Document any mismatches as high-confidence investigation leads in the plan.**

### 0.7.4 Document Feasibility Result

For each claim, categorize as:
- **FEASIBLE**: Source code confirms the behavior exists
- **PARTIAL**: Some of the behavior exists, but not all (document what's missing)
- **NOT_FEASIBLE**: The behavior does not exist in the codebase — requires upstream work

**If any claim is NOT_FEASIBLE:**
1. Document which claims are not feasible and why
2. Propose a revised scope that tests what IS feasible
3. Note the gap as a follow-up ticket recommendation
4. Add this to the Jira comment so the orchestrator's plan review has full context

**If all claims are FEASIBLE:** Proceed to Phase 0.8.

---

## Phase 0.8: Already-Implemented Gate (MANDATORY)

**Read 1-2 key files identified in Phase 0.7. If the issue is already done, STOP immediately — no worktree, no Jira transition.**

This gate prevents the most expensive waste pattern: creating a full worktree, branch, and Jira transition before discovering the work was already merged.

### 0.8.1 Check for Implementation Evidence

Using the file paths discovered in Phase 0.7, read the most critical file(s) that would change if the issue were implemented:

```bash
# Read the primary file(s) that would be modified
# Look for: the specific function, field, handler, or component mentioned in the issue
```

**Signs the issue is already implemented:**
- The exact fix described in the issue is already present in the code
- The feature/field/endpoint already exists with the correct behavior
- Tests for the described scenario already pass
- A recent commit message references this issue or describes the same fix

**Signs the issue is genuinely new work:**
- The bug/missing behavior is clearly absent from the code
- The file structure or function signature described doesn't match reality (needs fix)
- No evidence of the fix in git log for the relevant files

### 0.8.2 Decision Branch

**If issue appears ALREADY IMPLEMENTED:**

```bash
# Add comment to Jira explaining what was found
npx tsx ~/.claude/skills/issues/add_comment.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"body\": \"**Already Implemented — Stopping Plan Creation**\n\nThis issue appears to already be implemented.\n\n**Evidence:**\n- [describe what was found and in which file]\n- [relevant code snippet or line reference]\n\n**Recommendation:** Verify in dev environment and close if confirmed. If behavior is still broken, update the issue with more specific reproduction steps.\"}"

# STOP — do not proceed to Phase 1, do not create worktree
echo "STOPPED: Issue $ARGUMENTS.issue appears already implemented. See Jira comment."
exit 0
```

**If issue is genuinely new work:** Proceed to Phase 1.

---

## Phase 1: Session Initialization

### 0.0 Verify AgentDB Memory Connectivity

**CRITICAL: Verify agent memory is connected before proceeding.**

```bash
# Test agentdb connectivity by checking database health
npx tsx ~/.claude/skills/agentdb/db_get_health.ts '{}'
npx tsx ~/.claude/skills/agentdb/db_get_stats.ts '{}'
```

**Expected output:**
- `db_get_health` returns `{ status: "healthy", ... }`
- `db_get_stats` returns record counts

**If health check fails:**
- In ECS: Check AGENTDB_MCP_URL environment variable
- In local: Check agentdb is installed and configured
- Log warning but continue (memory features will be limited)

### 0.1 GUARDRAIL: Track Session Costs

**NEW GUARDRAIL: Track session costs per issue to detect high-cost anti-patterns.**

```typescript
// Track session costs per issue
const sessionCostKey = `session-costs-$ARGUMENTS.issue`;
const existingCosts = await bash(`npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"task": "${sessionCostKey}", "k": 1}'`);

let sessionData = existingCosts?.value
  ? JSON.parse(existingCosts.value)
  : { sessions: 0, estimatedCost: 0, firstSession: new Date().toISOString() };

sessionData.sessions += 1;
sessionData.estimatedCost += 12; // Estimated cost per session
sessionData.lastSession = new Date().toISOString();

// Warn if high session count
const SESSION_WARNING_THRESHOLD = 20;
const SESSION_BLOCK_THRESHOLD = 50;

if (sessionData.sessions >= SESSION_BLOCK_THRESHOLD) {
  # Add warning comment to Jira
  npx tsx ~/.claude/skills/issues/add_comment.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"body\": \"**Session Limit Warning**\\n\\n**Sessions:** ${sessionData.sessions}\\n**Estimated Cost:** \$${sessionData.estimatedCost}\\n**Duration:** ${sessionData.firstSession} to now\\n\\nThis issue has exceeded the session threshold.\\n\\n**Recommended Actions:**\\n1. Review if issue scope is appropriate\\n2. Consider splitting into smaller issues\\n3. Investigate why so many sessions were needed\\n4. Check for recurring blockers\\n\\n**Adding \`high-session-count\` label for tracking.**\"}"

  # Add label for tracking
  issue=$(npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "labels"}')
  currentLabels=$(echo "$issue" | jq -r '.fields.labels // []')

  if ! echo "$currentLabels" | jq -e '.[] | select(. == "high-session-count")' > /dev/null; then
    updatedLabels=$(echo "$currentLabels" | jq '. + ["high-session-count"]')
    npx tsx ~/.claude/skills/issues/update_issue.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"labels\": $updatedLabels}"
  fi
} else if (sessionData.sessions >= SESSION_WARNING_THRESHOLD) {
  console.warn(`Session count (${sessionData.sessions}) approaching threshold for $ARGUMENTS.issue`);
}

// Store updated session data
await bash(`npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{"session_id": "${TENANT_NAMESPACE}", "task": "${sessionCostKey}", "input": ${JSON.stringify(sessionData)}, "output": "Session tracked", "reward": 0.5, "success": false, "critique": "Session cost tracking"}'`);
```

### 0.2 Load Persistent Memory

```bash
# Search for issue context in AgentDB
npx tsx ~/.claude/skills/agentdb/recall_query.ts "{\"query\": \"$ARGUMENTS.issue context\", \"k\": 10}"
```

### 0.4 Parallel Context Gathering

```bash
# All in parallel:
npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query_id": "plan-$ARGUMENTS.issue", "query": "$ARGUMENTS.issue context and related discussions"}' &
npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "key,summary,status,description,labels,issuetype,priority,comment"}' &
wait
```

### 0.4.1 MANDATORY: Parse ALL Jira Comments for Updated Evidence

**Do NOT plan from the description alone.** Comments frequently contain updated evidence,
expanded scope, or corrections to the original description. After fetching the issue:

1. Read EVERY comment on the issue (not just the description)
2. Extract any scope changes, additional failure scenarios, or environment details
3. If a comment contradicts or expands the description, the comment takes precedence
4. Incorporate all comment evidence into the implementation plan scope

**Common patterns that comments reveal:**
- "Also failing on GET, not just POST" → expands affected endpoints
- "All environments affected" → expands deployment scope beyond dev
- "Updated evidence" → may change root cause hypothesis
- "Additional investigation areas" → new investigation leads

### 0.5 Check Blockers

- If `needs-human` label exists -> STOP and notify user
- If dependencies are blocked -> STOP and notify user

### 0.6 Read Repository CLAUDE.md

```typescript
Task tool:
  subagent_type: "Explore"
  prompt: "Find and summarize relevant patterns in [repo] CLAUDE.md for implementing $ARGUMENTS.issue"
```

---

## Phase 1: Claim Issue and Classify Type

### 1.1 Transition to In Progress and Set Step Label

```bash
# Get current issue state
issue=$(npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "key,status,labels"}')

# Transition to In Progress if not already
status=$(echo "$issue" | jq -r '.fields.status.name')
if [ "$status" != "In Progress" ]; then
  npx tsx ~/.claude/skills/issues/list_transitions.ts '{"issue_key": "$ARGUMENTS.issue"}'
  npx tsx ~/.claude/skills/issues/transition_issue.ts '{"issue_key": "$ARGUMENTS.issue", "transition_id": "<in-progress-id>", "comment": "Starting planning phase"}'
fi

# MANDATORY: Set step label for agent tracking
labels=$(echo "$issue" | jq -r '.fields.labels // [] | map(select(startswith("step:") | not)) | . + ["step:planning"] | @json')
npx tsx ~/.claude/skills/issues/update_issue.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"labels\": $labels}"
```

**Step Label Purpose:** The `step:planning` label allows other agents to immediately recognize that this issue is in the planning phase. When they query for issues, they can filter by step label to find issues at specific stages without reading full issue details.

### 1.2 MANDATORY: Classify Issue Type

**Analyze the issue and classify into one of these categories:**

| Issue Type | Indicators | Validation Requirements |
|------------|------------|------------------------|
| **UI_DISPLAY** | Frontend, visual, layout, render, CSS, styling | Browser screenshot, visual inspection |
| **UI_INTERACTION** | Click, button, form, navigation, routing, modal | Browser testing with DevTools open, console check |
| **UI_STATE** | Race condition, loading, async, state, store, null check | Browser testing with slow network, console check |
| **API_ENDPOINT** | Lambda, handler, REST, request, response | curl output, status codes, CloudWatch logs |
| **API_INTEGRATION** | Auth, token, Stripe, Cognito, external service | API response verification, error handling |
| **BACKEND_DATA** | DynamoDB, database, query, index, data | Database query verification |
| **BACKEND_LOGIC** | Calculation, validation, business logic | Unit test coverage |

**Store classification in memory:**
```bash
# Determine issue type and store
issue_type=$(determine_issue_type "$issue_description" "$affected_files")

issue_type_data=$(cat <<EOF
{
  "type": "$issue_type",
  "requiresBrowserTesting": $([ "${issue_type:0:3}" = "UI_" ] && echo "true" || echo "false"),
  "requiresConsoleCheck": $([ "${issue_type:0:3}" = "UI_" ] && echo "true" || echo "false"),
  "requiresApiTesting": $([ "${issue_type:0:4}" = "API_" ] && echo "true" || echo "false"),
  "requiresSlowNetworkTest": $([ "$issue_type" = "UI_STATE" ] && echo "true" || echo "false")
}
EOF
)

npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts "{\"session_id\": \"${TENANT_NAMESPACE}\", \"task\": \"issue-type-$ARGUMENTS.issue\", \"input\": $(echo "$issue_type_data" | jq -c .), \"output\": \"\", \"reward\": 0.5, \"success\": false, \"critique\": \"Issue classified\"}"
```

**Update Jira with classification:**
```bash
# Build comment body based on issue type
comment_body="**Issue Classification**

**Type:** ${issueType}
**Repository:** ${repository}

**Validation Requirements:**"

if [[ $issueType == UI_* ]]; then
  comment_body+="
- [ ] Manual browser testing required
- [ ] Console must be checked for errors"
fi

if [ "$issueType" = "UI_STATE" ]; then
  comment_body+="
- [ ] Slow network testing required"
fi

if [[ $issueType == API_* ]]; then
  comment_body+="
- [ ] API endpoint testing with curl"
fi

if [[ $issueType == BACKEND_* ]]; then
  comment_body+="
- [ ] Backend verification required"
fi

npx tsx ~/.claude/skills/issues/add_comment.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"body\": $(echo "$comment_body" | jq -Rs .)}"
```

### 1.3 GUARDRAIL: Multi-Repo Issue Detection

**NEW GUARDRAIL: Detect multi-repo issues early to prevent coordination overhead.**

Multi-repo issues (like PROJ-358) have **56% higher costs** due to coordination complexity.

```typescript
// Check for multi-repo indicators
const labels = issue.fields.labels || [];
const repoLabels = labels.filter(l => l.startsWith("repo-"));

if (repoLabels.length > 1) {
  const repos = repoLabels.map(l => l.replace("repo-", ""));
  const reposStr = repos.join(", ");

  // CRITICAL: Determine PRIMARY repo by searching for the code to change.
  // Extract key terms from the issue description and grep each candidate repo.
  // The repo with actual matches is the primary; don't just pick the first label.
  //
  // Example:
  //   description mentions "GatewayResponse" and "Access-Control-Allow-Origin"
  //   grep -r "GatewayResponse" ${PROJECT_ROOT}/repo-a/ → 0 hits
  //   grep -r "GatewayResponse" ${PROJECT_ROOT}/repo-b/ → 5 hits  ← primary
  //
  // Steps:
  // 1. Extract 2-3 distinctive terms from the issue description (resource names,
  //    config keys, error messages — NOT generic words like "fix" or "update")
  // 2. grep -rl "<term>" ${PROJECT_ROOT}/<repo>/ for each candidate repo
  // 3. The repo with the most hits is the primary repo for worktree creation
  // 4. If no repo has hits, STOP and ask the user — don't guess

  npx tsx ~/.claude/skills/issues/add_comment.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"body\": \"**Multi-Repository Issue Detected**\\n\\n**Repositories:** ${reposStr}\\n\\nMulti-repo issues have **56% higher costs** due to coordination overhead.\\n\\n**Recommended Approach:**\\n1. **Split into sequential issues** if repos are independent\\n2. **Or proceed with coordination** — implement primary repo first\\n\\n**Proceeding with single multi-repo implementation.**\\n**Note:** Consider splitting if this becomes complex.\"}";

  // Store multi-repo context
  await bash(`npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{"session_id": "${TENANT_NAMESPACE}", "task": "multi-repo-$ARGUMENTS.issue", "input": {"repos": ${JSON.stringify(repos)}, "primaryRepo": "${repos[0]}", "detectedAt": "${new Date().toISOString()}"}, "output": "Multi-repo detected", "reward": 0.5, "success": true, "critique": "Multi-repo context stored"}'`);
}
```

---

## Phase 2: Create Worktree and Branch (MANDATORY)

> **CRITICAL:** This phase is MANDATORY. The `enforce-worktree.sh` hook will BLOCK all file modifications unless you are in a worktree based on `origin/main`.

**Worktree-based workflow isolates work, enables parallel development, and ensures all changes go through PR review.**

### 2.1 Determine Repository Name

Determine the repository name from issue context, Jira labels (`repo-*`), or current directory.

### 2.2 MANDATORY: Create Worktree from origin/main

```bash
# Navigate to main repo
cd ${PROJECT_ROOT}/<repo>

# CRITICAL: Fetch latest origin/main to ensure worktree is based on current tip
git fetch origin main

# Create worktree with feature branch based on origin/main
git worktree add -b $ARGUMENTS.issue/<short-description> ../worktrees/<repo>-$ARGUMENTS.issue origin/main

# Navigate to worktree
cd ${PROJECT_ROOT}/worktrees/<repo>-$ARGUMENTS.issue

# Push branch to origin (required for PR creation later)
git push -u origin $ARGUMENTS.issue/<short-description>
```

**Why `origin/main`?**
- Ensures you start from the latest code
- Prevents merge conflicts with concurrent work
- Required by `enforce-worktree.sh` hook
- Creates clean PR diffs

### 2.3 Install Pre-Commit Guard

```bash
# Block working documents from being committed to repo root
cat > .git/hooks/pre-commit << 'HOOK'
#!/bin/sh
if git diff --cached --name-only | grep -E '^[^/]+\.md$' | grep -v -E '^(README|CLAUDE|TESTING|CHANGELOG|CONTRIBUTING|LICENSE)\.md$'; then
  echo "BLOCKED: Working .md file in repo root. Remove before committing."
  exit 1
fi
HOOK
chmod +x .git/hooks/pre-commit
```

### 2.4 Verify Worktree Creation

```bash
# Verify you're in a worktree
git rev-parse --git-dir  # Should contain ".git/worktrees/"

# Verify branch is based on origin/main
git merge-base --is-ancestor origin/main HEAD  # Should return 0 (success)
```

### 2.5 Store Worktree Info in Memory

```bash
# Store worktree information
worktree_data=$(cat <<EOF
{
  "repo": "$repo",
  "worktreePath": "${PROJECT_ROOT}/worktrees/${repo}-$ARGUMENTS.issue",
  "branch": "$ARGUMENTS.issue/$short_description",
  "basedOn": "origin/main",
  "createdAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
)

npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts "{\"session_id\": \"${TENANT_NAMESPACE}\", \"task\": \"worktree-$ARGUMENTS.issue\", \"input\": $(echo "$worktree_data" | jq -c .), \"output\": \"Worktree created\", \"reward\": 1.0, \"success\": true, \"critique\": \"Ready for implementation\"}"
```

### 2.6 Write Workflow Context File

After worktree creation, write `.agent-context.json` so downstream commands (`/implement`, `/review`, `/fix-pr`, `/resolve-pr`) can skip redundant API calls:

```bash
cat > .agent-context.json <<EOF
{
  "issueKey": "$ARGUMENTS.issue",
  "issueType": "$issue_type",
  "issueSummary": "$issue_summary",
  "repo": "$repo",
  "branch": "$branch",
  "worktreePath": "$(pwd)",
  "createdAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
```

### 2.6 Store Workflow Context in Memory

```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts "{\"session_id\": \"${TENANT_NAMESPACE}\", \"task\": \"active-workflow-$ARGUMENTS.issue\", \"input\": {\"issue_key\": \"$ARGUMENTS.issue\", \"step\": \"planning\", \"repo\": \"$repo\", \"worktreePath\": \"$(pwd)\", \"branch\": \"$branch\"}, \"output\": \"\", \"reward\": 0.5, \"success\": false, \"critique\": \"Workflow started\"}"
```

### 2.7 Failure Recovery

**If worktree already exists:**
```bash
# Remove stale worktree and recreate
git worktree remove ../worktrees/<repo>-$ARGUMENTS.issue --force
git worktree prune
# Then retry step 2.2
```

**If branch already exists on remote:**
```bash
# Delete remote branch and recreate
git push origin --delete $ARGUMENTS.issue/<short-description>
# Then retry step 2.2
```

---

## Phase 3: Planning with MANDATORY Validation Criteria

### 3.1 Write Implementation Plan

1. Load brainstorming skill if complex
2. Analyze the code changes needed
3. Write implementation plan with TDD test scenarios

**Implementation plan MUST include the following sections:**

#### Domain Alignment (if domain model available)
- **Bounded Context:** {ContextName}
- **Affected Aggregates:** [list]
- **New/Modified Commands:** [list]
- **New/Modified Events:** [list]
- **CML Update Required:** Yes/No -- if yes, add as final implementation step

#### Files to Change
[List of files with brief description of changes]

**Path verification (MANDATORY):** After listing each file path, verify it:
- For files to **edit**: run `ls <path>` to confirm the file exists
- For files to **create**: run `ls <parent-directory>/` to confirm the parent directory exists
- If the Jira description references a path that doesn't match the repo structure (e.g., `pkg/models/` when the repo uses `models/`), use the correct path from the repo and note the discrepancy

#### Tests to Write
[List of test files and test scenarios]

#### Implementation Steps
[Ordered list of implementation steps following TDD approach]

#### Test Infrastructure Validation (PROJECT-SPECIFIC)

**Every implementation plan MUST include this section to ensure test infrastructure is not forgotten.**

- **Required test data fixtures:** [list specific fixtures from test-data or "none"]
- **E2E test coverage:** [new tests to write / existing tests to modify / "existing coverage sufficient"]
- **Mockoon mock updates:** [endpoints affected or "none"]
- **Dashboard BOM impact:** [new artifact version tracked / "no change"]
- **Pipeline BOM impact:** [new Lambda functions / "no change"] (ref: project-docs/plans/2026-03-02-pipeline-bom-design.md)
- **Test data setup steps:** Commands to seed/reset test data for this feature
- **Test data teardown steps:** Commands to clean up after testing

### 3.2 MANDATORY: Define Validation Criteria

**Every implementation plan MUST include specific validation criteria that /validate will enforce.**

**For UI Issues (UI_DISPLAY, UI_INTERACTION, UI_STATE):**
```markdown
## Validation Criteria (MANDATORY - /validate will enforce these)

### Manual Browser Testing Required
- [ ] **Test 1:** Navigate to [specific URL] and verify [specific behavior]
- [ ] **Test 2:** Click [specific element] and verify [expected result]
- [ ] **Test 3:** [For UI_STATE] Throttle network to "Slow 3G" and verify [behavior]

### Console Requirements
- [ ] Open DevTools Console before testing
- [ ] Complete all test scenarios
- [ ] Verify zero errors in console (warnings from third-party libs OK)
- [ ] Screenshot console output as evidence

### Evidence Artifacts Required
- [ ] Screenshot of working feature
- [ ] Screenshot of console (showing no errors)
- [ ] [For UI_STATE] Screenshot with slow network test
```

**For API Issues (API_ENDPOINT, API_INTEGRATION):**
```markdown
## Validation Criteria (MANDATORY - /validate will enforce these)

### API Endpoint Testing Required
- [ ] **Test 1:** curl [endpoint] with [valid payload] -> expect [status/response]
- [ ] **Test 2:** curl [endpoint] with [invalid payload] -> expect [error response]
- [ ] **Test 3:** curl [endpoint] without auth -> expect 401

### Evidence Artifacts Required
- [ ] curl output showing successful response
- [ ] curl output showing error handling
- [ ] CloudWatch logs showing no errors
```

### 3.3 Update Jira with Plan AND Validation Criteria

```bash
# Build validation criteria comment
comment_body="**Implementation Plan**

[plan content]

---

## VALIDATION CRITERIA (MANDATORY)

**These criteria MUST be satisfied before marking DONE. The /validate command will enforce these.**

### Required Tests"

for test in "${validationCriteria.tests[@]}"; do
  comment_body+="
- [ ] $test"
done

comment_body+="

### Required Evidence"

for evidence in "${validationCriteria.evidence[@]}"; do
  comment_body+="
- [ ] $evidence"
done

comment_body+="

### Issue Type: ${issueType}"

if [[ $issueType == UI_* ]]; then
  comment_body+="
**Manual browser testing with DevTools console open is REQUIRED**"
fi

if [ "$issueType" = "UI_STATE" ]; then
  comment_body+="
**Slow network testing is REQUIRED (race condition risk)**"
fi

npx tsx ~/.claude/skills/issues/add_comment.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"body\": $(echo "$comment_body" | jq -Rs .)}"
```

### 3.3.5 MANDATORY: Validation Criteria Quality Gate

**Purpose:** Ensure validation criteria are specific enough to prevent first-pass failures.

```typescript
// Quality checks for validation criteria
const qualityIssues = [];

// Check 1: Tests must be specific (not vague)
const vaguePatterns = [
  "verify it works",
  "check that it",
  "make sure",
  "should work",
  "test the feature",
  "validate functionality"
];

for (const test of validationCriteria.tests) {
  const testLower = test.toLowerCase();
  for (const pattern of vaguePatterns) {
    if (testLower.includes(pattern)) {
      qualityIssues.push(`Vague test: "${test}" - use specific, measurable criteria`);
      break;
    }
  }
}

// Check 2: Tests must have expected outcomes
for (const test of validationCriteria.tests) {
  if (!test.includes("verify") && !test.includes("assert") &&
      !test.includes("expect") && !test.includes("should") &&
      !test.includes("confirm") && !test.includes("check")) {
    qualityIssues.push(`Test missing expected outcome: "${test}"`);
  }
}

// Check 3: Evidence must match tests (1:1 ratio minimum)
if (validationCriteria.evidence.length < validationCriteria.tests.length) {
  qualityIssues.push(
    `Insufficient evidence: ${validationCriteria.evidence.length} evidence items for ${validationCriteria.tests.length} tests`
  );
}

// Check 4: UI issues need console check
if (issueType.startsWith("UI_") && !validationCriteria.requiresConsoleCheck) {
  qualityIssues.push("UI issue missing console check requirement");
  validationCriteria.requiresConsoleCheck = true; // Auto-fix
}

// Check 5: UI_STATE issues need slow network test
if (issueType === "UI_STATE" && !validationCriteria.requiresSlowNetworkTest) {
  qualityIssues.push("UI_STATE issue missing slow network test requirement");
  validationCriteria.requiresSlowNetworkTest = true; // Auto-fix
}

// Check 6: API issues need response validation
if (issueType.startsWith("API_") && !validationCriteria.requiresApiTesting) {
  qualityIssues.push("API issue missing API testing requirement");
  validationCriteria.requiresApiTesting = true; // Auto-fix
}

// Check 7: Must have at least 2 test scenarios
if (validationCriteria.tests.length < 2) {
  qualityIssues.push(
    `Insufficient test coverage: ${validationCriteria.tests.length} tests (minimum 2 required)`
  );
}

// Check 8: Tests should cover happy path and error case
const hasHappyPath = validationCriteria.tests.some(t =>
  !t.toLowerCase().includes("error") && !t.toLowerCase().includes("fail")
);
const hasErrorCase = validationCriteria.tests.some(t =>
  t.toLowerCase().includes("error") || t.toLowerCase().includes("fail") ||
  t.toLowerCase().includes("invalid") || t.toLowerCase().includes("empty")
);

if (!hasHappyPath) {
  qualityIssues.push("Missing happy path test scenario");
}
if (!hasErrorCase && !issueType.includes("DISPLAY")) {
  qualityIssues.push("Missing error/edge case test scenario (recommended)");
}

// Check 9: Test infrastructure section completeness (PROJECT-SPECIFIC)
if (!testInfrastructure) {
  qualityIssues.push("Missing test infrastructure validation section");
}

// Report quality issues
if (qualityIssues.length > 0) {
  console.warn(`Validation Criteria Quality Issues (${qualityIssues.length}):`);
  qualityIssues.forEach((issue, i) => console.warn(`  ${i + 1}. ${issue}`));

  // For critical issues (vague tests, insufficient coverage), prompt for improvement
  const criticalIssues = qualityIssues.filter(i =>
    i.includes("Vague test") || i.includes("Insufficient")
  );

  if (criticalIssues.length > 0) {
    console.error("CRITICAL: Validation criteria quality too low.");
    console.error("Improve criteria before proceeding to prevent validation failures.");

    // Don't block, but add warning to Jira
    qualityIssuesText=$(printf '%s\n' "${qualityIssues[@]}" | sed 's/^/- /')
    npx tsx ~/.claude/skills/issues/add_comment.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"body\": \"**Validation Criteria Quality Warning**\\n\\nThe following quality issues were detected:\\n${qualityIssuesText}\\n\\n**Impact:** Low-quality criteria increase validation retry rates.\\n\\n**Recommendation:** Review and improve criteria specificity before running \`/validate\`.\"}"
  }
}

// Calculate quality score
const qualityScore = Math.max(0, 1 - (qualityIssues.length * 0.15));
validationCriteria.qualityScore = qualityScore;
validationCriteria.qualityIssues = qualityIssues;

console.log(`Validation criteria quality score: ${(qualityScore * 100).toFixed(0)}%`);
```

### 3.4 Store Validation Criteria in Memory

```bash
# Store validation criteria
validation_criteria=$(cat <<EOF
{
  "issueType": "$issue_type",
  "tests": [
    "Navigate to /organization/limitations and verify applications load",
    "Toggle application enabled state and verify no console errors",
    "Throttle to Slow 3G, refresh, verify applications still load"
  ],
  "evidence": [
    "Screenshot of working feature",
    "Screenshot of console (no errors)",
    "Screenshot with slow network test"
  ],
  "requiresBrowserTesting": true,
  "requiresConsoleCheck": true,
  "requiresSlowNetworkTest": $([ "$issue_type" = "UI_STATE" ] && echo "true" || echo "false")
}
EOF
)

npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts "{\"session_id\": \"${TENANT_NAMESPACE}\", \"task\": \"validation-criteria-$ARGUMENTS.issue\", \"input\": $(echo "$validation_criteria" | jq -c .), \"output\": \"\", \"reward\": 0.5, \"success\": false, \"critique\": \"Validation criteria defined\"}"
```

### 3.4.5: E2E Spec Authoring (MANDATORY for observable changes)

**If `$E2E_REPO` is unset:** Log "E2E_REPO not configured — skipping E2E spec authoring." and proceed.

**Otherwise:**
Call `/e2e-write $ARGUMENTS` to author the spec for this issue.

- If spec was already written at `/issue` or `/bug` creation time, `/e2e-write` skips generation
  and confirms `e2e.spec-path` in checkpoint.
- If `e2e.not-applicable: true` is set, no spec will be generated.
- On completion, `e2e.spec-path` and `e2e.draft-pr-number` are in checkpoint.

This must complete before implementation begins so the RED gate has a spec to test against.

---

### 3.5 Store Implementation Plan in Memory

```bash
# Store implementation plan
impl_plan_data=$(cat <<EOF
{
  "repo": "$repo",
  "worktreePath": "$worktree_path",
  "branch": "$branch",
  "issueType": "$issue_type",
  "plan": "$plan_summary",
  "filesToChange": ["file1", "file2"],
  "testsToWrite": ["test1", "test2"],
  "status": "planned",
  "createdAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
)

npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts "{\"session_id\": \"${TENANT_NAMESPACE}\", \"task\": \"impl-plan-$ARGUMENTS.issue\", \"input\": $(echo "$impl_plan_data" | jq -c .), \"output\": \"Plan created\", \"reward\": 1.0, \"success\": true, \"critique\": \"Ready for implementation\"}"
```

### 3.6 MANDATORY: Store Implementation Context in Memory

**After creating the implementation plan, store it in memory for cross-session access:**

```bash
# Store implementation context
impl_context=$(cat <<EOF
{
  "issue_key": "$ARGUMENTS.issue",
  "plan": "$implementation_plan",
  "validation_criteria": $validation_criteria,
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
)

npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts "{\"session_id\": \"${TENANT_NAMESPACE}\", \"task\": \"impl-$ARGUMENTS.issue\", \"input\": $(echo "$impl_context" | jq -c .), \"output\": \"Context stored\", \"reward\": 1.0, \"success\": true, \"critique\": \"Implementation context ready\"}"
```

**This enables:**
- Session resume without re-reading issue details
- Subagent context injection from parent workflow
- Validation criteria lookup by `/validate` command
- Cross-session continuity for multi-day implementations

**IMPORTANT:** Do NOT skip this step. The `/validate` command expects to find this memory key.

### 3.7 MANDATORY: Add Outcome Label for Routing

**After successfully storing the implementation plan, add the outcome label to enable daemon routing.**

```bash
# MANDATORY: Add outcome label for routing to /implement
issue=$(npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "key,labels"}')

# Filter out any existing step/outcome labels and add new outcome
updatedLabels=$(echo "$issue" | jq -r '.fields.labels // [] | map(select(startswith("step:") or startswith("outcome:") | not)) | . + ["outcome:success-plan-created"] | @json')

npx tsx ~/.claude/skills/issues/update_issue.ts "{\"issue_key\": \"$ARGUMENTS.issue\", \"labels\": $updatedLabels, \"notify_users\": false}"
```

**Purpose:** The `outcome:success-plan-created` label enables the daemon's `ready-to-implement` route to automatically pick up this issue and run `/implement`. Without this label, the daemon cannot distinguish between issues that have completed planning and those still in progress.

---

## Completion Summary

After Phase 3 completes, provide summary:

```markdown
## Implementation Plan Complete: $ARGUMENTS.issue

**Status:** PLANNED (ready for implementation)
**Issue Type:** [UI_INTERACTION/API_ENDPOINT/etc.]
**Repository:** <repo>
**Worktree:** <worktree-path>
**Branch:** <branch-name>

### Implementation Plan Summary
[Brief summary of what will be done]

### Files to Change
- [list of files]

### Tests to Write
- [list of tests]

### Test Infrastructure Impact
- Test data fixtures: [summary]
- E2E tests: [summary]
- Mockoon mocks: [summary]
- BOM impact: [summary]

### Validation Criteria Captured
${validationCriteria.tests.map(t => `- [ ] ${t}`).join('\n')}

### Next Step

Run the implementation command:
```bash
/implement $ARGUMENTS.issue
```
```

---

## Anti-Patterns (AUTOMATIC FAILURE)

- Missing Jira evidence updates = FAILURE
- Not classifying issue type = FAILURE
- Not defining validation criteria in implementation plan = FAILURE
- Not storing validation criteria for /validate = FAILURE
- Not storing implementation plan in memory = FAILURE
- **Not storing implementation context with key `impl-$ARGUMENTS.issue` = FAILURE** (required for /validate)
- **Not adding `outcome:success-plan-created` label = FAILURE** (required for daemon routing to /implement)
- Creating worktree from wrong branch = FAILURE
- Not pushing branch to origin = FAILURE
- **Missing test infrastructure validation section = FAILURE** (test-data, e2e-tests, Mockoon, BOM assessment required)
- **Writing an `implementation-plan.md` or `IMPLEMENTATION_PLAN.md` file to the worktree = FAILURE** (plans live in Jira comments + agentdb ONLY, never as committed files)
- **Skipping file discovery and feasibility scan (Phase 0.7) = FAILURE** (prevents planning unimplementable work)
- **Skipping already-implemented gate (Phase 0.8) = FAILURE** (prevents creating worktrees/transitions for done work)

---

**START NOW: Create the TodoWrite items above, then begin Phase 0.**

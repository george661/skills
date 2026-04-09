<!-- MODEL_TIER: local -->
---
description: Collect evidence artifacts for validation report
arguments:
  - name: issue
    description: Jira issue key (e.g., PROJ-123)
    required: true
  - name: repo
    description: Repository name
    required: true
  - name: test_results_path
    description: Path to test results file written by validate-run-tests (default /tmp/validate-<issue>-test-results.txt)
    required: false
---

# Collect Validation Evidence: $ARGUMENTS.issue

## Purpose

Gather evidence artifacts (screenshots, logs, API responses) to attach to the validation report.
Called by the `/validate` orchestrator — do not run standalone.

## Phase 0.5: Determine Authentication Requirements

Read the checkpoint to determine if this issue requires authenticated screenshots:

```bash
# Read the visual impact checkpoint set by Phase 0.6 of validate-run-tests
checkpoint=$(python3 ~/.claude/hooks/checkpoint.py load $ARGUMENTS.issue val.phase0.6-complete 2>/dev/null || echo "{}")
has_visual_effects=$(echo "$checkpoint" | jq -r ".has_visual_effects // false")
ui_paths=$(echo "$checkpoint" | jq -r ".ui_paths // []")

# Determine if authentication is required for screenshots
requires_auth_screenshots="false"
if [ "$has_visual_effects" = "true" ] || [ "$ARGUMENTS.repo" = "frontend-app" ] || [ "$ARGUMENTS.repo" = "e2e-tests" ]; then
  requires_auth_screenshots="true"
fi

echo "Authentication required for screenshots: $requires_auth_screenshots"
```

## Phase 0: Resolve Authentication (Conditional)

**MANDATORY before collecting authenticated runtime evidence.** Skip this phase when `requires_auth_screenshots` is false.

```bash
# Skip auth resolution for issues that don't require authenticated screenshots
if [ "$requires_auth_screenshots" = "false" ]; then
  echo "Skipping auth resolution - not required for this issue type"
  AUTH_AVAILABLE="false"
else
  echo "Proceeding with auth resolution for authenticated screenshots..."
  AUTH_AVAILABLE="true"
fi
```

### Determine the environment

Extract from deploy URL:
- `dev.example.com` → env = `dev`
- `demo.example.com` → env = `demo`
- `platform.example.com` → env = `production`

### Auth config for Playwright scripts

**Note: This section only applies when requires_auth_screenshots is true.**

All Playwright scripts (`screenshot.ts`, `console-check.ts`, `network-check.ts`) accept an `auth` parameter.
The `auth` field MUST be **nested inside the JSON object** — passing `role` at the top level silently redirects
to the login page without throwing an error.

**CORRECT — `auth` is a nested object:**
```bash
npx tsx ~/.claude/skills/playwright/screenshot.ts \
  '{"url": "...", "outputPath": "/tmp/...", "auth": {"env": "dev", "role": "org_admin"}}'
```

**WRONG — `role` at top level silently redirects to login:**
```bash
# '{"url": "...", "role": "org_admin"}'  ← DO NOT USE — auth not nested
```

The scripts automatically load `e2e-config.json` (searched in: cwd/.claude/, PROJECT_ROOT/.claude/, ~/.claude/),
resolve SSM credentials, and log in before navigating. They detect login-page redirects and report
`authRedirectDetected: true` on failure.

**If a screenshot shows the login/auth page:** The cause is almost always the wrong auth schema (role not
nested), NOT missing credentials. Re-run with the correct nested schema before declaring auth unavailable.

### Auth token for curl (API evidence)

**Only resolve when authentication is required:**

```bash
# Skip token resolution for basic screenshot collection
if [ "$requires_auth_screenshots" = "true" ]; then
  # Use SRP auth via cognito-srp-token.js with credentials from testData.json
  
  # 1. Get credentials from testData.json by role
  ROLE="admin"  # or app_admin, org_admin, org_member — match the issue's required role
  # Map "admin" to "global_admin" for testData.json lookup
  TD_ROLE=$( [ "$ROLE" = "admin" ] && echo "global_admin" || echo "$ROLE" )
  CREDS=$(cat $PROJECT_ROOT/e2e-tests/tests/fixtures/testData.json | jq -r --arg role "$TD_ROLE" '[.[] | select(.role == $role)][0] | "\(.email) \(.password)"')
  EMAIL=$(echo "$CREDS" | awk '{print $1}')
  PASSWORD=$(echo "$CREDS" | awk '{print $2}')
  
  # 2. Get JWT token via SRP auth
  TOKEN=$(node ~/.claude/skills/cognito-srp-token.js "$EMAIL" "$PASSWORD" dev)
  
  if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
    echo "AUTH_FAILED: SRP auth failed"
    AUTH_AVAILABLE="false"
  else
    echo "AUTH_SUCCESS: Token resolved"
    AUTH_AVAILABLE="true"
  fi
else
  echo "Skipping token resolution - basic screenshots only"
  TOKEN=""
  AUTH_AVAILABLE="false"
fi
```

**Why SRP, not USER_PASSWORD_AUTH:** Cognito clients do not have USER_PASSWORD_AUTH enabled.
The `oauth-test-cli` client supports USER_SRP_AUTH with no client secret.

**If testData.json is missing:** `cd $PROJECT_ROOT/e2e-tests && npm run test-data:download`

**If SRP auth fails for authenticated issues:** Mark EVIDENCE_QUALITY as INSUFFICIENT with reason "AUTH_FAILED: SRP auth failed".
Do NOT silently collect unauthenticated screenshots of login pages and report them as evidence.

## Phase 1: Determine Evidence Needs

Based on `$ARGUMENTS.repo`, issue classification, and authentication requirements, collect MANDATORY runtime evidence.

**Code-reading and unit test output alone are NOT sufficient evidence.** At least one runtime
artifact must be collected that proves the deployed system works.

### Decision Table for Evidence Collection

| Issue Type | has_visual_effects | code_repo | Screenshot Method | API Auth Required |
|---|---|---|---|---|
| UI Issue | true | frontend-app/e2e-tests | Authenticated Playwright | Yes |
| Backend Issue | true | any | Authenticated Playwright | Yes |
| Backend Issue | false | NOT frontend-app/e2e-tests | Basic Playwright (no auth) | Only for API calls |
| Infrastructure | false | any | Basic Playwright (no auth) | Yes for API calls |

### How to collect runtime evidence

Read the target repo's CLAUDE.md `## Deployment Verification` → `### Runtime Evidence Collection`
section for repo-specific instructions on how to collect runtime artifacts.

### Evidence Quality Rules

- **INSUFFICIENT**: Only code snippets from source files, only unit test pass counts, only PR merge confirmation, OR screenshots of login pages instead of authenticated content
- **SUFFICIENT**: At least one authenticated runtime artifact (curl response with valid token, authenticated screenshot, CloudWatch log) plus supporting code/test evidence
- **STRONG**: Multiple authenticated runtime artifacts covering happy path and error cases

If runtime evidence cannot be collected (environment down, auth failed, tool unavailable),
document why and mark evidence as INSUFFICIENT with explanation.

### Evidence Types by Repository

| Evidence Type | When | Tool |
|---|---|---|
| Screenshots | UI changes **AND** backend changes with visible UI effects | Playwright screenshot skill **with auth if required** |
| Console errors | UI changes **AND** backend changes with visible UI effects | Playwright console-check skill **with auth if required** |
| API responses | API changes (lambda-functions) | curl **with Bearer token** |
| CloudWatch logs | Lambda/infra changes (lambda-functions, core-infra) | AWS CLI |
| Build logs | Always | Concourse fly CLI |

### Backend Repos With Visual Effects (Conditional Authentication)

**CRITICAL:** Backend repos (lambda-functions, go-common, core-infra) frequently produce visible UI behavior — session listings, token balances, marketplace entries, organization data, sidebar items, datasets. When the issue description or acceptance criteria reference anything a user *sees* or *navigates to*, authenticated Playwright screenshots are REQUIRED from the affected frontend-app pages.

**For issues without visual effects:** Use basic screenshots without authentication to verify page loads and basic functionality.

Affected frontend-app paths are pre-computed by the orchestrator and passed in the enrichment context. If explicit paths were provided, use them. If not, infer from the issue description:
- Session/marketplace changes → `https://dev.example.com/marketplace`
- Token/balance changes → `https://dev.example.com/tokens`
- Organization/membership → `https://dev.example.com/settings/organization`
- Sidebar/navigation → `https://dev.example.com/marketplace`
- Datasets → `https://dev.example.com/datasets`
- Admin dashboard → `https://dev.example.com/admin`

### HARD GATE — ZERO EXCEPTIONS

The following are NOT valid evidence and MUST NOT be substituted:
- "Bundle size looks good"
- "Unit tests pass"
- "Playwright not configured"
- Code snippets from source files
- PR merge confirmation

If you cannot collect runtime evidence, STOP and report failure with:
```
EVIDENCE_QUALITY: INSUFFICIENT
REASON: Unable to collect runtime evidence. {specific error}
```
Do not invent a substitute. Do not proceed to verdict.

---

## Phase 2: Collect Screenshots (Conditional Authentication)

Screenshot collection method depends on the issue type and authentication requirements:

### Path A: Authenticated Screenshots (when requires_auth_screenshots = true)

For **UI issues and backend issues with visual effects** — requires valid authentication:

```bash
# Only proceed if authentication was successful
if [ "$AUTH_AVAILABLE" = "true" ] && [ "$requires_auth_screenshots" = "true" ]; then
  # Capture key screens showing the change — WITH AUTHENTICATION
  npx tsx ~/.claude/skills/playwright/screenshot.ts '{"url": "https://<env>.platform.example.com/<path>", "outputPath": "/tmp/validate-$ARGUMENTS.issue-<name>.png", "auth": {"env": "<env>", "role": "admin"}}'
  
  # Also capture console errors to verify no JS errors on the page
  npx tsx ~/.claude/skills/playwright/console-check.ts '{"url": "https://<env>.platform.example.com/<path>", "auth": {"env": "<env>", "role": "admin"}, "failOnError": true}'
  
  AUTH_SCREENSHOT_STATUS="AUTHENTICATED"
  
elif [ "$requires_auth_screenshots" = "true" ] && [ "$AUTH_AVAILABLE" != "true" ]; then
  # Auth failed for an issue that requires it
  echo "AUTH_FAILED: Cannot collect authenticated screenshots - auth resolution failed"
  AUTH_SCREENSHOT_STATUS="AUTH_FAILED"
  EVIDENCE_QUALITY="INSUFFICIENT"
  EVIDENCE_QUALITY_REASON="AUTH_FAILED: Authentication required for visual validation but auth resolution failed"
else
  AUTH_SCREENSHOT_STATUS="AUTH_NOT_REQUIRED"
fi
```

### Path B: Basic Screenshots (when requires_auth_screenshots = false)

For **backend issues without visual effects** — basic page load verification:

```bash
# Collect basic screenshots without authentication
if [ "$requires_auth_screenshots" = "false" ]; then
  # Capture basic page loads to verify deployment and basic functionality
  npx tsx ~/.claude/skills/playwright/screenshot.ts '{"url": "https://<env>.platform.example.com/<path>", "outputPath": "/tmp/validate-$ARGUMENTS.issue-basic-<name>.png"}'
  
  # Check console for critical errors (deployment issues)
  npx tsx ~/.claude/skills/playwright/console-check.ts '{"url": "https://<env>.platform.example.com/<path>", "failOnError": false}'
  
  AUTH_SCREENSHOT_STATUS="AUTH_NOT_REQUIRED"
fi
```

**CRITICAL: Check the output for `authRedirectDetected`.** If `true`, the screenshot shows the login page, NOT the actual page. For Path A (authenticated), this indicates auth failure and marks EVIDENCE_QUALITY as INSUFFICIENT. For Path B (basic), redirects to login are expected and acceptable.

## Phase 3: Collect Logs

```bash
# Recent CloudWatch logs for affected Lambda (if lambda-functions)
aws logs filter-log-events --log-group-name "/aws/lambda/<function>" --start-time <15-min-ago-epoch> --limit 20

# Recent Concourse build output
npx tsx ~/.claude/skills/ci/list_builds.ts '{"pipeline": "$ARGUMENTS.repo", "count": 1}'
```

## Phase 4: Collect API Responses (if applicable)

For each validation criterion that involves an API:
```bash
# Use the $TOKEN resolved in Phase 0 only if available
if [ "$AUTH_AVAILABLE" = "true" ] && [ -n "$TOKEN" ]; then
  curl -s https://<env>.platform.example.com/api/<path> -H "Authorization: Bearer $TOKEN" | jq . > /tmp/validate-$ARGUMENTS.issue-api-<name>.json
elif [ "$requires_auth_screenshots" = "false" ]; then
  # For basic issues, attempt unauthenticated API calls where appropriate
  curl -s https://<env>.platform.example.com/api/<path> | jq . > /tmp/validate-$ARGUMENTS.issue-api-<name>.json
fi
```

**Do not use placeholder `<token>` strings.** The token must be resolved in Phase 0 or omitted for basic collection.

## Phase 5: Output Evidence Manifest

Write to `/tmp/validate-$ARGUMENTS.issue-evidence.txt` AND print to stdout:

```bash
# Determine overall auth status for the manifest
if [ "$AUTH_SCREENSHOT_STATUS" = "AUTHENTICATED" ]; then
  MANIFEST_AUTH_STATUS="AUTHENTICATED"
elif [ "$AUTH_SCREENSHOT_STATUS" = "AUTH_FAILED" ]; then
  MANIFEST_AUTH_STATUS="AUTH_FAILED"
else
  MANIFEST_AUTH_STATUS="AUTH_NOT_REQUIRED"
fi

# Set evidence quality based on auth requirements and success
if [ "$requires_auth_screenshots" = "true" ] && [ "$AUTH_SCREENSHOT_STATUS" = "AUTH_FAILED" ]; then
  EVIDENCE_QUALITY="INSUFFICIENT"
  EVIDENCE_QUALITY_REASON="AUTH_FAILED: Authentication required for visual validation but auth resolution failed"
elif [ -z "$EVIDENCE_QUALITY" ]; then
  # Set based on actual evidence collected
  EVIDENCE_QUALITY="SUFFICIENT"  # Will be refined based on actual artifacts
fi
```

```
EVIDENCE_START
TYPE: screenshot
PATH: /tmp/validate-$ARGUMENTS.issue-<name>.png
DESCRIPTION: <what it shows>
AUTHENTICATED: true | false
---
TYPE: api_response
PATH: /tmp/validate-$ARGUMENTS.issue-api-<name>.json
DESCRIPTION: <what endpoint, what it proves>
AUTHENTICATED: true | false
---
TYPE: log
CONTENT: <relevant log lines, max 50>
DESCRIPTION: <what it proves>
---
EVIDENCE_END
ARTIFACT_COUNT: <N>
RUNTIME_EVIDENCE_COUNT: <count of non-code-reading artifacts>
AUTHENTICATED_EVIDENCE_COUNT: <count of artifacts collected with valid auth>
EVIDENCE_QUALITY: STRONG | SUFFICIENT | INSUFFICIENT
EVIDENCE_QUALITY_REASON: <if INSUFFICIENT: what's missing and why>
AUTH_STATUS: AUTHENTICATED | AUTH_FAILED | AUTH_NOT_REQUIRED
```

If EVIDENCE_QUALITY is INSUFFICIENT, include a clear statement of what runtime evidence
could not be collected and why (e.g., "AUTH_FAILED: SRP credentials not accessible",
"AUTH_REDIRECT: Screenshots show login page, not authenticated content").

## Phase 5.5: Upload Evidence to Jira (MANDATORY)

For each evidence artifact collected:

```bash
npx tsx ~/.claude/skills/jira/add_attachment.ts '{"issue_key": "$ARGUMENTS.issue", "file_path": "<artifact_path>", "filename": "<descriptive_name>.png"}'
```

If upload fails: log warning but do not block verdict. Evidence exists locally even if Jira upload fails.

After all uploads, add a Jira comment summarizing evidence:
```bash
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "$ARGUMENTS.issue", "body": "Validation evidence uploaded: {count} artifacts. Types: {screenshot|api_response|terraform_plan|log}"}'
```

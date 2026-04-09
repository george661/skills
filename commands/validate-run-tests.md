<!-- MODEL_TIER: local -->
---
description: Execute validation tests against the deployed environment
arguments:
  - name: issue
    description: Jira issue key (e.g., PROJ-123)
    required: true
  - name: repo
    description: Repository name (e.g., lambda-functions)
    required: true
---

# Run Validation Tests: $ARGUMENTS.issue

## Purpose

Execute validation tests against the deployed environment using criteria stored on the Jira issue.
Called by the `/validate` orchestrator — do not run standalone.

## Phase 1: Load Validation Criteria

1. Fetch issue with full description and comments:
   ```bash
   npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "$ARGUMENTS.issue", "fields": "description,comment", "expand": "renderedFields"}'
   ```

2. Extract the **Validation Criteria** section from the description. These are the specific checks
   that must pass. Each criterion should map to a testable assertion.

3. If no validation criteria found, check comments for a "Validation Criteria" heading
   (sometimes added by `/implement`).

4. If still none found: STOP and report "No validation criteria found on issue."

## Phase 1.5: Resolve Authentication

**MANDATORY for all UI and API validation.** Authentication is required to access protected pages and API endpoints.

### Determine the environment

Extract the environment from the deploy URL:
- `dev.example.com` → env = `dev`
- `demo.example.com` → env = `demo`
- `platform.example.com` → env = `production`

### For Playwright-based tests (UI validation)

All Playwright scripts (`console-check.ts`, `network-check.ts`, `screenshot.ts`) accept an `auth` parameter.
**Always pass auth when testing protected pages:**

```bash
# Auth config object to include in every Playwright call
AUTH='{"env": "<env>", "role": "admin"}'

# Example: console-check with authentication
npx tsx ~/.claude/skills/playwright/console-check.ts '{"url": "https://<env>.platform.example.com/<path>", "auth": '"$AUTH"', "failOnError": true}'
```

The Playwright scripts will:
1. Load `e2e-config.json` (searched in: cwd/.claude/, PROJECT_ROOT/.claude/, ~/.claude/)
2. Resolve SSM credentials for the specified role and environment
3. Log in via the login form before navigating to the target URL
4. **Detect login redirects** — if the page redirects to /login after navigation, the script reports `authRedirectDetected: true` and fails, preventing false-positive validation

### For API validation (curl)

Obtain an auth token via **SRP auth** using `cognito-srp-token.js` and credentials from
`e2e-tests/tests/fixtures/testData.json` (seeded by test-data).

**YOU MUST FOLLOW THESE STEPS EXACTLY. DO NOT SKIP OR MODIFY ANY STEP.**

#### Step A: Ensure testData.json exists
```bash
if [ ! -f $PROJECT_ROOT/e2e-tests/tests/fixtures/testData.json ]; then
  cd $PROJECT_ROOT/e2e-tests && npm install --silent 2>/dev/null && npm run test-data:download
fi
```

#### Step B: Extract credentials
```bash
ROLE="org_admin"
CREDS=$(cat $PROJECT_ROOT/e2e-tests/tests/fixtures/testData.json | jq -r --arg role "$ROLE" '[.[] | select(.role == $role)][0] | "\(.email) \(.password) \(.orgId)"')
EMAIL=$(echo "$CREDS" | awk '{print $1}')
PASSWORD=$(echo "$CREDS" | awk '{print $2}')
ORG_ID=$(echo "$CREDS" | awk '{print $3}')
```

#### Step C: Get JWT token via SRP
```bash
TOKEN=$(node ~/.claude/skills/cognito-srp-token.js "$EMAIL" "$PASSWORD" dev)
```

#### Step D: Verify token before proceeding
**STOP HERE if the token is empty or does not start with `eyJ`.** Do not proceed to API calls
with an invalid token. Report `AUTH_STATUS: AUTH_FAILED` immediately.
```bash
if [ -z "$TOKEN" ] || [[ ! "$TOKEN" == eyJ* ]]; then
  echo "AUTH FAILED: TOKEN is empty or invalid. Value: $(echo "$TOKEN" | head -c 50)"
  echo "AUTH_STATUS: AUTH_FAILED"
  # Still output test results with AUTHENTICATED: false for each criterion
fi
```

#### Step E: Use the token in API calls
```bash
curl -s -w '\nHTTP %{http_code}' \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  https://api.dev.example.com/<path>
```

**CRITICAL RULES:**
- The `Authorization` header format is exactly: `Bearer <token>` (capital B, one space, raw JWT)
- Do NOT URL-encode the token
- Do NOT wrap the token in quotes inside the header value
- Do NOT use any other auth method (IAM SigV4, API keys, etc.) — this API uses JWT Bearer auth
- If you get "Authorization header requires 'Credential' parameter", your header is **malformed** —
  debug the curl command, do not conclude "the API uses IAM auth"
- Include `X-Organization-Id` header for org-scoped endpoints

**Why SRP, not USER_PASSWORD_AUTH:** The Cognito user pool clients do not have the
USER_PASSWORD_AUTH flow enabled. The `oauth-test-cli` client supports USER_SRP_AUTH
and has no client secret, making it suitable for headless API testing.

**If testData.json is missing**, download it:
```bash
cd $PROJECT_ROOT/e2e-tests && npm install --silent 2>/dev/null && npm run test-data:download
```

**If SRP auth fails:** Check that the user exists in Cognito (test-data seeds users).
Mark the test as FAIL with reason "AUTH_UNAVAILABLE: SRP auth failed for <email>".
Do NOT silently skip authentication and report unauthenticated results as passing.
Do NOT rationalize auth failure as an infrastructure issue — if the script fails, report it as AUTH_FAILED.

## Phase 2: Classify Validation Type

Based on `$ARGUMENTS.repo` and the criteria content, determine which test types to run:

| Repo Pattern | Test Type | Tool |
|---|---|---|
| `frontend-app` | UI + API | Playwright with auth (console-check, network-check, screenshot) |
| `lambda-functions` | API only | curl with Bearer token against deployed env |
| `core-infra` | Infrastructure | AWS CLI checks (CloudWatch, DynamoDB, etc.) |
| `e2e-tests` | E2E journeys | Playwright with auth against deployed env |
| Other | API + smoke | curl with Bearer token against deployed endpoints |

## Phase 3: Execute Tests

### For API validation (lambda-functions, core-infra):

Run each validation criterion as an API call against the deployed environment:
```bash
curl -s -w "\n%{http_code}" https://<env>.platform.example.com/api/<path> -H "Authorization: Bearer $TOKEN"
```

Use the environment URL matching the deployment target (dev/demo/prod).
**The $TOKEN variable must be resolved in Phase 1.5.** Do not use placeholder `<token>` strings.

### For UI validation (frontend-app, e2e-tests):

Use Playwright scripts with authentication:
```bash
# Console check — detects JS errors on authenticated pages
npx tsx ~/.claude/skills/playwright/console-check.ts '{"url": "https://<env>.platform.example.com/<path>", "auth": {"env": "<env>", "role": "admin"}, "failOnError": true}'

# Network check — detects failed API calls (4xx, 5xx) on authenticated pages
npx tsx ~/.claude/skills/playwright/network-check.ts '{"url": "https://<env>.platform.example.com/<path>", "auth": {"env": "<env>", "role": "admin"}, "failOnError": true}'
```

**CRITICAL: Check the `authRedirectDetected` field in the output.** If `true`, the page requires auth but the login failed — mark the criterion as FAIL, not PASS.

### For infrastructure validation (core-infra):

Check AWS resources:
```bash
aws cloudwatch get-metric-statistics --namespace <ns> --metric-name <metric> ...
aws dynamodb describe-table --table-name <table> ...
```

## Phase 4: Output Results

Write structured results to `/tmp/validate-$ARGUMENTS.issue-test-results.txt` AND print to stdout:

```
TEST_RESULTS_START
CRITERION: <criterion text>
RESULT: PASS | FAIL
EVIDENCE: <response body, screenshot path, or metric value>
AUTHENTICATED: true | false
---
CRITERION: <next criterion>
RESULT: PASS | FAIL
EVIDENCE: <evidence>
AUTHENTICATED: true | false
---
TEST_RESULTS_END
PASSED: <N>
FAILED: <M>
TOTAL: <N+M>
AUTH_STATUS: AUTHENTICATED | AUTH_FAILED | AUTH_NOT_REQUIRED
```

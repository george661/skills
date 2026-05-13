{% meta description="Check deployment status for a merged Jira issue" doc_type="command" tier="contract" /%}

{% input name="issue" type="string" required="true" description="Jira issue key (e.g., PROJ-123)" /%}

{% output name="DEPLOY_STATUS" type="string" description="DEPLOYED | FAILED | IN_PROGRESS | NEEDS_DEPLOY | UNKNOWN" /%}
{% output name="REPO" type="string" description="Repository name from repo-* label" /%}
{% output name="PIPELINE" type="string" description="CI pipeline name" /%}
{% output name="BUILD_ID" type="string" description="CI build identifier" /%}
{% output name="BUILD_STATUS" type="string" description="succeeded | failed | started | pending" /%}
{% output name="ENV_URL" type="string" description="Environment base URL from repo CLAUDE.md or env-* labels (optional)" required_when="false" /%}
{% output name="DEPLOY_GAP_REASON" type="string" description="Brief description of deployment gap (only if DEPLOY_STATUS is NEEDS_DEPLOY)" required_when="DEPLOY_STATUS == \"NEEDS_DEPLOY\"" /%}

# Check Deployment Status: {% $inputs.issue %}

## Purpose

Verify that the code for this issue has been deployed to the target environment.
This is called by the `/validate` orchestrator — do not run standalone.

{% phase name="Load Issue Context" %}

1. Fetch the issue from Jira:
   {% run skill="jira/get_issue" %}{"issue_key": "{% $inputs.issue %}", "fields": "status,labels,comment"}{% /run %}

2. Verify issue is in VALIDATION status. If not, STOP and report the current status.

3. Extract the `repo-*` label to determine which repository was changed.

{% /phase %}

{% phase name="Check CI Pipeline on Main" %}

1. Find the most recent build for the affected repo's pipeline:
   ```bash
   # For lambda-functions: jobs are named "deploy-{domain}-functions-dev", not "main"
   # For all other repos: try "deploy-dev" first, then fall back to no job filter
   PIPELINE_NAME=$(echo "$REPO_LABEL" | sed 's/repo-//')
   if [ "$PIPELINE_NAME" = "lambda-functions" ]; then
     # List all recent builds (no job filter) and look for most recent deploy-* job
     npx tsx ~/.claude/skills/ci/list_builds.ts "{\"pipeline\": \"lambda-functions\", \"count\": 10}"
   else
     npx tsx ~/.claude/skills/ci/list_builds.ts "{\"pipeline\": \"$PIPELINE_NAME\", \"count\": 5}" 2>/dev/null ||      npx tsx ~/.claude/skills/ci/list_builds.ts "{\"pipeline\": \"$PIPELINE_NAME\", \"count\": 5}"
   fi
   ```

2. Check the build status:
   - **succeeded** → deployment confirmed
   - **failed** → report failure details, STOP
   - **started/pending** → report "build in progress", STOP

{% /phase %}

{% phase name="Verify Deployment Artifacts" %}

Read the target repo's CLAUDE.md (look for `## Deployment Verification` section).
Follow the repo-specific instructions to verify the code is actually deployed.

1. Find the PR merge date from Jira comments (look for `pr:` label, extract repo/PR number):
   ```bash
   PR_LABEL=$(echo "$LABELS" | grep -o 'pr:[^ ]*')
   if [ -n "$PR_LABEL" ]; then
     REPO_NAME=$(echo "$PR_LABEL" | cut -d: -f2 | cut -d/ -f1)
     PR_NUM=$(echo "$PR_LABEL" | cut -d/ -f2)
     npx tsx ~/.claude/skills/bitbucket/get_pull_request.ts "{\"repo_slug\": \"$REPO_NAME\", \"pull_request_id\": $PR_NUM}"
   fi
   ```

2. Follow the repo's "How to verify deployment after merge" instructions.
   Compare the deployment timestamp/build date against the PR merge date.

3. If the repo's CLAUDE.md has no Deployment Verification section,
   fall back to the pipeline status check from the previous phase.

If deployment artifact is older than the PR merge, output `DEPLOY_STATUS: NEEDS_DEPLOY`.

**Commit correlation (minimal):** If a `pr:<repo>/<number>` label exists, fetch the PR's
merge commit hash and verify it appears in the deployed build's git range. If no PR label,
skip this check — pipeline status alone is sufficient.

{% /phase %}

{% phase name="Output Result" %}

Print a structured result block that the orchestrator will parse:

```
DEPLOY_STATUS: DEPLOYED | FAILED | IN_PROGRESS | NEEDS_DEPLOY | UNKNOWN
REPO: <repo-name>
PIPELINE: <pipeline-name>
BUILD_ID: <id>
BUILD_STATUS: <status>
ENV_URL: <environment base URL from repo CLAUDE.md>
DEPLOY_GAP_REASON: <if NEEDS_DEPLOY: brief description of the gap>
```

**Environment URL resolution**: Read from the repo's CLAUDE.md `## Deployment Verification`
section (look for `### Environment URLs`). If not found, check for `env-*` labels on the
issue or `TENANT_ENV` in the environment.

If FAILED, include the build log summary (first 50 lines of failure output).

{% /phase %}












# Check Deployment Status: GW-5189

## Purpose

Verify that the code for issue GW-5189 has been deployed to the target environment.
This is called by the `/validate` orchestrator — do not run standalone.

## Phase: Load Issue Context



1. Fetch the issue from Jira:
   Call the issues/get_issue skill:
```bash
npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "GW-5189", "fields": "status,labels,comment"}'
```

2. Verify issue is in VALIDATION status. If not, STOP and report the current status.

3. Extract the `repo-*` label to determine which repository was changed.




## Phase: Check CI Pipeline on Main



1. Find the most recent build for the affected repo's pipeline:
   ```bash
   PIPELINE_NAME=$(echo "$REPO_LABEL" | sed 's/repo-//')
   npx tsx ~/.claude/skills/ci/list_builds.ts "{\"pipeline\": \"$PIPELINE_NAME\", \"count\": 5}"
   ```

2. Check the build status:
   - **succeeded** → deployment confirmed
   - **failed** → report failure details, STOP
   - **started/pending** → report "build in progress", STOP




## Phase: Verify Deployment Artifacts



Read the target repo's CLAUDE.md (look for `## Deployment Verification` section).
Follow the repo-specific instructions to verify the code is actually deployed.





## OUTPUT CONTRACT

Emit the following fields in your response:

- `DEPLOY_STATUS` (string): DEPLOYED | FAILED | IN_PROGRESS | NEEDS_DEPLOY | UNKNOWN
- `REPO` (string): Repository name from repo-* label
- `PIPELINE` (string): CI pipeline name
- `BUILD_ID` (string): Latest build ID for the pipeline
- `BUILD_STATUS` (string): succeeded | failed | started | pending
- `ENV_URL` (string): URL of deployed environment (if applicable)
{% meta doc_type="command" description="Check deployment status for a merged Jira issue" /%}

{% input name="issue" type="string" required="true" description="Jira issue key (e.g., PROJ-123)" /%}

{% output name="DEPLOY_STATUS" type="string" description="DEPLOYED | FAILED | IN_PROGRESS | NEEDS_DEPLOY | UNKNOWN" /%}
{% output name="REPO" type="string" description="Repository name from repo-* label" /%}
{% output name="PIPELINE" type="string" description="CI pipeline name" /%}
{% output name="BUILD_ID" type="string" description="Latest build ID for the pipeline" /%}
{% output name="BUILD_STATUS" type="string" description="succeeded | failed | started | pending" /%}
{% output name="ENV_URL" type="string" description="URL of deployed environment (if applicable)" /%}

# Check Deployment Status: {% $inputs.issue %}

## Purpose

Verify that the code for issue {% $inputs.issue %} has been deployed to the target environment.
This is called by the `/validate` orchestrator — do not run standalone.

{% phase name="Load Issue Context" %}

1. Fetch the issue from Jira:
   {% run skill="issues/get_issue" %}{"issue_key": "{% $inputs.issue %}", "fields": "status,labels,comment"}{% /run %}

2. Verify issue is in VALIDATION status. If not, STOP and report the current status.

3. Extract the `repo-*` label to determine which repository was changed.

{% /phase %}

{% phase name="Check CI Pipeline on Main" %}

1. Find the most recent build for the affected repo's pipeline:
   ```bash
   PIPELINE_NAME=$(echo "$REPO_LABEL" | sed 's/repo-//')
   npx tsx ~/.claude/skills/ci/list_builds.ts "{\"pipeline\": \"$PIPELINE_NAME\", \"count\": 5}"
   ```

2. Check the build status:
   - **succeeded** → deployment confirmed
   - **failed** → report failure details, STOP
   - **started/pending** → report "build in progress", STOP

{% /phase %}

{% phase name="Verify Deployment Artifacts" %}

Read the target repo's CLAUDE.md (look for `## Deployment Verification` section).
Follow the repo-specific instructions to verify the code is actually deployed.

{% /phase %}

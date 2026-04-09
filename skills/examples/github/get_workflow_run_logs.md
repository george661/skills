# get_workflow_run_logs

Get logs from a GitHub Actions workflow run for debugging CI failures.

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `owner` | Yes | Repository owner (org or user) |
| `repo` | Yes | Repository name |
| `run_id` | Yes | Workflow run ID |

## Workflow for Debugging

1. Use `list_workflow_runs` to find the failed run
2. Get `run_id` from the failed workflow
3. Use this tool to download logs
4. Parse logs for error details

## Examples

### Get logs for a failed run

```bash
# Step 1: Find the failed run
npx tsx .claude/skills/github-mcp/list_workflow_runs.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "branch": "${TENANT_BRANCH_PREFIX}${TENANT_PROJECT}-123"}'

# Step 2: Get logs for the run
npx tsx .claude/skills/github-mcp/get_workflow_run_logs.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "run_id": 12345678}'
```

### Download logs for analysis

```bash
npx tsx .claude/skills/github-mcp/download_workflow_run_logs.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "run_id": 12345678}'
```

## Return Format

Returns a ZIP file containing logs for all jobs in the workflow run.

The ZIP contains:
```
workflow-run-logs/
├── job1/
│   ├── 1_Set up job.txt
│   ├── 2_Checkout.txt
│   ├── 3_Install dependencies.txt
│   ├── 4_Run tests.txt
│   └── 5_Post Checkout.txt
├── job2/
│   └── ...
```

## Getting Individual Job Logs

For more targeted debugging, you can get logs for a specific job:

```bash
# List jobs in the run
npx tsx .claude/skills/github-mcp/list_jobs_for_workflow_run.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "run_id": 12345678}'

# Get logs for specific job
npx tsx .claude/skills/github-mcp/get_job_logs.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "job_id": 98765432}'
```

## Bitbucket Equivalent

`npx tsx .claude/skills/bitbucket-mcp/get_pipeline_step_log.ts` - Note differences:
- GitHub downloads logs as ZIP (all jobs) or per-job
- Bitbucket returns logs per step
- GitHub requires run_id → job_id chain
- Bitbucket requires pipeline_uuid → step_uuid chain

### Equivalent Workflow

| GitHub | Bitbucket |
|--------|-----------|
| `list_workflow_runs` | `listPipelineRuns` |
| `list_jobs_for_workflow_run` | `getPipelineSteps` |
| `get_job_logs` | `getPipelineStepLogs` |

## Common Error Patterns

Look for these in the logs:
- `Error:` or `error:` - Direct error messages
- `FAILED` - Test failures
- `npm ERR!` - Node package issues
- `Exit code: 1` - Non-zero exit codes

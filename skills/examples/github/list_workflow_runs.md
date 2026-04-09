# list_workflow_runs

List GitHub Actions workflow runs for a repository. Use to monitor CI/CD status.

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `owner` | Yes | Repository owner (org or user) |
| `repo` | Yes | Repository name |
| `workflow_id` | No | Workflow file name or ID to filter |
| `branch` | No | Filter by branch name |
| `event` | No | Filter by event type: `push`, `pull_request`, etc. |
| `status` | No | Filter by status: `queued`, `in_progress`, `completed` |
| `per_page` | No | Results per page (max 100) |

## Examples

### Get recent workflow runs

```bash
npx tsx .claude/skills/github-mcp/list_workflow_runs.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo"}'
```

### Get runs for a specific branch

```bash
npx tsx .claude/skills/github-mcp/list_workflow_runs.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "branch": "${TENANT_BRANCH_PREFIX}${TENANT_PROJECT}-123"}'
```

### Get runs for a specific workflow

```bash
npx tsx .claude/skills/github-mcp/list_workflow_runs.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "workflow_id": "ci.yml", "status": "completed", "per_page": 5}'
```

### Filter by event type

```bash
npx tsx .claude/skills/github-mcp/list_workflow_runs.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "event": "pull_request"}'
```

## Return Format

```json
{
  "total_count": 42,
  "workflow_runs": [
    {
      "id": 12345678,
      "name": "CI",
      "status": "completed",
      "conclusion": "success",
      "head_branch": "agent/PROJ-123",
      "head_sha": "abc123",
      "html_url": "https://github.com/owner/repo/actions/runs/12345678",
      "created_at": "2025-01-08T10:00:00Z",
      "updated_at": "2025-01-08T10:15:00Z"
    }
  ]
}
```

## Key Fields

| Field | Description |
|-------|-------------|
| `status` | `queued`, `in_progress`, `completed` |
| `conclusion` | `success`, `failure`, `cancelled`, `skipped` (when status=completed) |
| `head_branch` | Branch that triggered the workflow |

## Bitbucket Equivalent

`npx tsx .claude/skills/bitbucket-mcp/list_pipelines.ts` - Note parameter differences:
- `owner` (GitHub) = `workspace` (Bitbucket)
- `repo` (GitHub) = `repo_slug` (Bitbucket)
- `workflow_id` has no direct equivalent (Bitbucket uses single pipeline)
- `branch` (GitHub) = `target_branch` (Bitbucket)

### Status Mapping

| GitHub | Bitbucket | Meaning |
|--------|-----------|---------|
| `queued` | `PENDING` | Waiting to run |
| `in_progress` | `IN_PROGRESS` | Currently running |
| `completed` + `success` | `SUCCESSFUL` | Completed successfully |
| `completed` + `failure` | `FAILED` | Failed |
| `completed` + `cancelled` | `STOPPED` | Manually stopped |

## Next Steps

For failed runs, use `get_workflow_run` then `get_workflow_run_logs` to diagnose.

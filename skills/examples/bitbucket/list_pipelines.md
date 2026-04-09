# list_pipelines

List pipeline runs for a repository. Use to monitor CI/CD status.

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `repo_slug` | Yes | Repository slug |
| `sort` | No | Sort field (e.g., `-created_on` for newest first) |
| `fields` | No | Comma-separated fields to reduce payload |

## Field Selection

```
values.uuid,values.state.name,values.created_on,values.target.ref_name
```

**Common fields:**
- `values.uuid` - Pipeline UUID (needed for step logs)
- `values.state.name` - Status: `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`
- `values.state.result.name` - Result: `SUCCESSFUL`, `FAILED`, `STOPPED`
- `values.created_on` - Start timestamp
- `values.target.ref_name` - Branch name
- `values.duration_in_seconds` - Run duration

## Examples

### Get recent pipelines (newest first)

```bash
npx tsx .claude/skills/bitbucket-mcp/list_pipelines.ts '{"repo_slug": "my-repo", "sort": "-created_on", "fields": "values.uuid,values.state,values.target.ref_name,values.created_on"}'
```

### Check pipeline status for debugging

```bash
npx tsx .claude/skills/bitbucket-mcp/list_pipelines.ts '{"repo_slug": "my-repo", "sort": "-created_on", "fields": "values.uuid,values.state.name,values.state.result.name,values.target.ref_name"}'
```

## Return Format

```json
{
  "values": [
    {
      "uuid": "{abc-123}",
      "state": { "name": "COMPLETED", "result": { "name": "FAILED" } },
      "target": { "ref_name": "feature/x" },
      "created_on": "2025-01-08T10:00:00Z"
    }
  ]
}
```

## Next Steps

For failed pipelines, use `list_pipeline_steps` then `get_pipeline_step_log` to diagnose.

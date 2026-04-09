# get_pipeline_step_log

Get the log output from a specific pipeline step. Essential for debugging failed builds.

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `repo_slug` | Yes | Repository slug |
| `pipeline_uuid` | Yes | Pipeline UUID from `list_pipelines` |
| `step_uuid` | Yes | Step UUID from `list_pipeline_steps` |

## Workflow

1. **List pipelines** to find the failed pipeline UUID
2. **List steps** to find the failed step UUID
3. **Get step log** to see error details

## Examples

### Step 1: Find failed pipeline

```bash
npx tsx .claude/skills/bitbucket-mcp/list_pipelines.ts '{"repo_slug": "my-repo", "sort": "-created_on", "fields": "values.uuid,values.state.result.name"}'
# Returns: uuid = "{abc-123}"
```

### Step 2: List pipeline steps

```bash
npx tsx .claude/skills/bitbucket-mcp/list_pipeline_steps.ts '{"repo_slug": "my-repo", "pipeline_uuid": "{abc-123}"}'
# Returns steps with their UUIDs and states
```

### Step 3: Get failed step log

```bash
npx tsx .claude/skills/bitbucket-mcp/get_pipeline_step_log.ts '{"repo_slug": "my-repo", "pipeline_uuid": "{abc-123}", "step_uuid": "{step-456}"}'
```

## Return Format

Returns raw log text containing:
- Command output
- Error messages
- Test failures
- Build errors

## Common Patterns

**Find test failures:**
Look for lines containing `FAILED`, `Error:`, or `AssertionError`

**Find build errors:**
Look for `npm ERR!`, `TypeScript error`, or exit codes

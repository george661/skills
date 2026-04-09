---
name: fly:list_builds
description: List recent builds on the Concourse target with optional pipeline and job filtering.
---

# list_builds

List recent builds on the Concourse target. Optionally filter by pipeline and/or job name, and control how many builds to return.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `count` | number | No | Number of builds to return (default: 25) |
| `pipeline` | string | No | Filter builds by pipeline name |
| `job` | string | No | Filter builds by job name (requires `pipeline` to be set) |

## Example

```bash
# List last 25 builds
npx tsx ~/.claude/skills/fly/list_builds.ts '{}'

# List last 10 builds
npx tsx ~/.claude/skills/fly/list_builds.ts '{"count": 10}'

# List builds for a specific pipeline
npx tsx ~/.claude/skills/fly/list_builds.ts '{"pipeline": "my-app"}'

# List builds for a specific job in a pipeline
npx tsx ~/.claude/skills/fly/list_builds.ts '{"pipeline": "my-app", "job": "build", "count": 5}'
```

## Response

```json
{
  "target": "my-concourse",
  "count": 5,
  "filters": {
    "pipeline": "my-app",
    "job": "build",
    "requested_count": 5
  },
  "builds": [
    {
      "id": 42,
      "team_name": "main",
      "name": "42",
      "status": "succeeded",
      "job_name": "build",
      "pipeline_name": "my-app",
      "start_time": 1700000000,
      "end_time": 1700000120
    }
  ]
}
```

## Notes

- Build statuses include: `pending`, `started`, `succeeded`, `failed`, `errored`, `aborted`
- When filtering by job, the pipeline parameter is required (job reference format is `pipeline/job`)
- Default count is 25 if not specified
- Builds are returned in reverse chronological order (newest first)

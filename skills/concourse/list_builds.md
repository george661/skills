---
name: concourse:list_builds
description: List builds for a job in a pipeline.
---

# list_builds

List builds for a specific job in a pipeline. Use this to check build history and monitor CI/CD status.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pipeline_name` | string | Yes | The name of the pipeline |
| `job_name` | string | Yes | The name of the job |
| `limit` | number | No | Maximum number of builds to return |

## Example

```typescript
// List all builds for a job
npx tsx ~/.claude/skills/concourse/list_builds.ts '{"pipeline_name": "my-pipeline", "job_name": "build"}'

// List last 5 builds
npx tsx ~/.claude/skills/concourse/list_builds.ts '{"pipeline_name": "my-pipeline", "job_name": "build", "limit": 5}'
```

## Notes

- The team name is loaded from credentials (CONCOURSE_TEAM)
- Returns an array of build objects ordered by most recent first
- Build statuses include: pending, started, succeeded, failed, errored, aborted
- Use the `limit` parameter to reduce response size

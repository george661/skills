---
name: concourse:list_jobs
description: List all jobs for a pipeline.
---

# list_jobs

List all jobs defined in a specific pipeline. Use this to discover available jobs and their current build status.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pipeline_name` | string | Yes | The name of the pipeline |

## Example

```typescript
// List all jobs in a pipeline
npx tsx ~/.claude/skills/concourse/list_jobs.ts '{"pipeline_name": "my-pipeline"}'
```

## Notes

- The team name is loaded from credentials (CONCOURSE_TEAM)
- Returns an array of job objects with name, pipeline_name, team_name, and build information
- Each job includes finished_build and next_build details when available

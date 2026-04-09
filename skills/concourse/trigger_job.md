---
name: concourse:trigger_job
description: Trigger a new build for a job in a pipeline.
---

# trigger_job

Trigger a new build for a specific job in a pipeline. Creates a new build and returns its details.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pipeline_name` | string | Yes | The name of the pipeline |
| `job_name` | string | Yes | The name of the job to trigger |

## Example

```typescript
// Trigger a job
npx tsx ~/.claude/skills/concourse/trigger_job.ts '{"pipeline_name": "my-pipeline", "job_name": "build"}'
```

## Notes

- The team name is loaded from credentials (CONCOURSE_TEAM)
- Returns the newly created build object with id, name, status, and job details
- Build statuses include: pending, started, succeeded, failed, errored, aborted

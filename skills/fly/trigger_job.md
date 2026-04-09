---
name: fly:trigger_job
description: Trigger a job in a Concourse pipeline and optionally watch its output.
---

# trigger_job

Trigger a job in a Concourse pipeline. Optionally watch the build output in real-time until completion.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pipeline_name` | string | Yes | The name of the pipeline containing the job |
| `job_name` | string | Yes | The name of the job to trigger |
| `watch` | boolean | No | Whether to watch the build output until completion (default: false) |

## Example

```bash
# Trigger a job (fire and forget)
npx tsx ~/.claude/skills/fly/trigger_job.ts '{"pipeline_name": "my-app", "job_name": "build"}'

# Trigger a job and watch the output
npx tsx ~/.claude/skills/fly/trigger_job.ts '{"pipeline_name": "my-app", "job_name": "build", "watch": true}'
```

## Response

```json
{
  "success": true,
  "target": "my-concourse",
  "pipeline_name": "my-app",
  "job_name": "build",
  "watched": false,
  "output": "started build 42"
}
```

## Notes

- The job reference format is `pipeline_name/job_name`
- When `watch` is true, the command blocks until the build completes and returns the full output
- When `watch` is false, the command returns immediately with the triggered build number
- If the job has required inputs that are not satisfied, the trigger will fail

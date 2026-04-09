---
name: concourse:pause_pipeline
description: Pause a pipeline to stop it from scheduling new builds.
---

# pause_pipeline

Pause a pipeline to prevent it from scheduling new builds. Paused pipelines will not trigger jobs from resource checks.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pipeline_name` | string | Yes | The name of the pipeline to pause |

## Example

```typescript
// Pause a pipeline
npx tsx ~/.claude/skills/concourse/pause_pipeline.ts '{"pipeline_name": "my-pipeline"}'
```

## Notes

- The team name is loaded from credentials (CONCOURSE_TEAM)
- Paused pipelines will not trigger builds from resource version changes
- Use unpause_pipeline to resume the pipeline
- Returns a success indicator on completion

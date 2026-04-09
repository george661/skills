---
name: concourse:unpause_pipeline
description: Unpause a pipeline to resume scheduling builds.
---

# unpause_pipeline

Unpause a pipeline to allow it to resume scheduling new builds from resource checks.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pipeline_name` | string | Yes | The name of the pipeline to unpause |

## Example

```typescript
// Unpause a pipeline
npx tsx ~/.claude/skills/concourse/unpause_pipeline.ts '{"pipeline_name": "my-pipeline"}'
```

## Notes

- The team name is loaded from credentials (CONCOURSE_TEAM)
- Unpaused pipelines will resume resource checking and build triggering
- Newly created pipelines start in a paused state and must be unpaused
- Returns a success indicator on completion

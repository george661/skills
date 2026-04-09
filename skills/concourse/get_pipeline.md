---
name: concourse:get_pipeline
description: Get detailed information about a specific pipeline.
---

# get_pipeline

Get detailed information about a specific pipeline in the configured Concourse team, including its paused status, groups, and team ownership.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pipeline_name` | string | Yes | The name of the pipeline |

## Example

```typescript
// Get pipeline details
npx tsx ~/.claude/skills/concourse/get_pipeline.ts '{"pipeline_name": "my-pipeline"}'
```

## Notes

- The team name is loaded from credentials (CONCOURSE_TEAM)
- Returns pipeline metadata including name, paused status, public flag, and team name

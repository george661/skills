---
name: concourse:get_pipeline_config
description: Get pipeline configuration (YAML) for a specific pipeline.
---

# get_pipeline_config

Get the full pipeline configuration for a specific pipeline. Returns the pipeline YAML definition including jobs, resources, and resource types.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pipeline_name` | string | Yes | The name of the pipeline |

## Example

```typescript
// Get pipeline configuration
npx tsx ~/.claude/skills/concourse/get_pipeline_config.ts '{"pipeline_name": "my-pipeline"}'
```

## Notes

- The team name is loaded from credentials (CONCOURSE_TEAM)
- Returns the pipeline config object with jobs, resources, and resource_types arrays
- The response includes a config version number used for set_pipeline operations

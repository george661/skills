---
name: fly:get_pipeline
description: Get the configuration of a Concourse pipeline as JSON.
---

# get_pipeline

Get the full configuration of a Concourse pipeline in JSON format, including resources, resource types, jobs, and groups.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pipeline_name` | string | Yes | The name of the pipeline to retrieve |

## Example

```bash
# Get pipeline configuration
npx tsx ~/.claude/skills/fly/get_pipeline.ts '{"pipeline_name": "my-app"}'
```

## Response

```json
{
  "target": "my-concourse",
  "pipeline_name": "my-app",
  "config": {
    "resources": [...],
    "resource_types": [...],
    "jobs": [...],
    "groups": [...]
  }
}
```

## Notes

- Returns the full pipeline YAML configuration parsed as JSON
- Useful for inspecting pipeline structure, resources, and job definitions
- The config object mirrors the pipeline YAML structure

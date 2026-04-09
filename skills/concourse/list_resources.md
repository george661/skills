---
name: concourse:list_resources
description: List all resources for a pipeline.
---

# list_resources

List all resources defined in a specific pipeline. Resources represent external inputs and outputs such as git repos, Docker images, and S3 buckets.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pipeline_name` | string | Yes | The name of the pipeline |

## Example

```typescript
// List all resources in a pipeline
npx tsx ~/.claude/skills/concourse/list_resources.ts '{"pipeline_name": "my-pipeline"}'
```

## Notes

- The team name is loaded from credentials (CONCOURSE_TEAM)
- Returns an array of resource objects with name, type, pipeline_name, and team_name
- Resource types include: git, docker-image, s3, time, semver, and custom resource types
- Each resource includes its last_checked timestamp and failing_to_check status

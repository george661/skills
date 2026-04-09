---
name: concourse:set_pipeline
description: Set or update a pipeline configuration.
---

# set_pipeline

Set or update the configuration for a pipeline. This creates the pipeline if it does not exist, or updates it if it does.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pipeline_name` | string | Yes | The name of the pipeline to create or update |
| `config` | object | Yes | The pipeline configuration object containing jobs, resources, and resource_types |

## Example

```typescript
// Set a pipeline configuration
npx tsx ~/.claude/skills/concourse/set_pipeline.ts '{"pipeline_name": "my-pipeline", "config": {"resources": [{"name": "repo", "type": "git", "source": {"uri": "https://github.com/org/repo.git", "branch": "main"}}], "jobs": [{"name": "build", "plan": [{"get": "repo", "trigger": true}, {"task": "run-tests", "file": "repo/ci/test.yml"}]}]}}'
```

## Notes

- The team name is loaded from credentials (CONCOURSE_TEAM)
- The config object should contain the full pipeline definition (jobs, resources, resource_types)
- Use get_pipeline_config to retrieve the current configuration before making changes
- Newly set pipelines start in a paused state; use unpause_pipeline to activate them
- The request body is sent as JSON (application/json)

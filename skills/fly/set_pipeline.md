---
name: fly:set_pipeline
description: Set (create or update) a Concourse pipeline from a YAML configuration file.
---

# set_pipeline

Set (create or update) a Concourse pipeline from a YAML configuration file. Uses `--non-interactive` mode to skip confirmation prompts.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pipeline_name` | string | Yes | The name of the pipeline to create or update |
| `pipeline_file` | string | Yes | Path to the pipeline YAML configuration file |
| `vars` | Record<string, string> | No | Key-value pairs to pass as pipeline variables via `--var` |

## Example

```bash
# Set a pipeline from a YAML file
npx tsx ~/.claude/skills/fly/set_pipeline.ts '{"pipeline_name": "my-app", "pipeline_file": "ci/pipeline.yml"}'

# Set a pipeline with variables
npx tsx ~/.claude/skills/fly/set_pipeline.ts '{"pipeline_name": "my-app", "pipeline_file": "ci/pipeline.yml", "vars": {"git-branch": "main", "env": "staging"}}'
```

## Response

```json
{
  "success": true,
  "target": "my-concourse",
  "pipeline_name": "my-app",
  "pipeline_file": "ci/pipeline.yml",
  "message": "pipeline created"
}
```

## Notes

- Uses `--non-interactive` to avoid confirmation prompts
- Variables are passed as `--var key=value` flags
- The pipeline is created in a paused state if it is new; use Concourse UI or API to unpause
- Validate the pipeline file first using `validate_pipeline` to catch errors

---
name: fly:validate_pipeline
description: Validate a Concourse pipeline YAML configuration file for syntax and structural errors.
---

# validate_pipeline

Validate a Concourse pipeline YAML configuration file. Checks for syntax errors, invalid resource types, missing dependencies, and other structural issues without deploying the pipeline.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pipeline_file` | string | Yes | Path to the pipeline YAML configuration file |

## Example

```bash
# Validate a pipeline configuration
npx tsx ~/.claude/skills/fly/validate_pipeline.ts '{"pipeline_file": "ci/pipeline.yml"}'

# Validate with absolute path
npx tsx ~/.claude/skills/fly/validate_pipeline.ts '{"pipeline_file": "/path/to/project/ci/pipeline.yml"}'
```

## Response

```json
{
  "valid": true,
  "target": "my-concourse",
  "pipeline_file": "ci/pipeline.yml",
  "message": "Pipeline configuration is valid."
}
```

On failure:

```json
{
  "valid": false,
  "target": "my-concourse",
  "pipeline_file": "ci/pipeline.yml",
  "errors": ["expected string at line 5, column 3"]
}
```

## Notes

- Does not deploy or modify any pipeline on the server
- Validates YAML syntax, resource definitions, job dependencies, and task configurations
- Use before `set_pipeline` to catch errors early

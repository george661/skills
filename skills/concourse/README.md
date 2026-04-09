---
name: concourse
description: Concourse CI REST API integration skills for pipeline and build management.
---

# Concourse CI Skills

REST-based skills for interacting with the Concourse CI API. These skills manage pipelines, jobs, builds, and resources.

## Setup

Configure credentials in one of three locations (checked in order):

### 1. Environment Variables

```bash
export CONCOURSE_URL="https://ci.example.com"
export CONCOURSE_TEAM="main"
# Either bearer token:
export CONCOURSE_TOKEN="your-bearer-token"
# Or username/password:
export CONCOURSE_USERNAME="your-username"
export CONCOURSE_PASSWORD="your-password"
```

### 2. .env File

Create a `.env` file in `$PROJECT_ROOT`:

```
CONCOURSE_URL=https://ci.example.com
CONCOURSE_TEAM=main
CONCOURSE_USERNAME=your-username
CONCOURSE_PASSWORD=your-password
```

### 3. ~/.claude/settings.json

```json
{
  "credentials": {
    "concourse": {
      "url": "https://ci.example.com",
      "team": "main",
      "username": "your-username",
      "password": "your-password"
    }
  }
}
```

## Authentication

The client supports two authentication methods:

1. **Bearer Token** -- If `CONCOURSE_TOKEN` is set, it is used directly as a bearer token.
2. **Username/Password** -- If no token is set, the client authenticates via `POST {url}/sky/issuer/token` using the password grant type. The resulting token is cached in memory for the session.

## Available Skills

| Skill | Description |
|-------|-------------|
| `list_pipelines` | List all pipelines for the team |
| `get_pipeline` | Get pipeline details |
| `get_pipeline_config` | Get pipeline configuration (YAML) |
| `set_pipeline` | Set or update pipeline configuration |
| `pause_pipeline` | Pause a pipeline |
| `unpause_pipeline` | Unpause a pipeline |
| `list_jobs` | List all jobs for a pipeline |
| `trigger_job` | Trigger a new build for a job |
| `get_build` | Get build details by ID |
| `list_builds` | List builds for a job |
| `list_resources` | List resources for a pipeline |

## Usage

```bash
# List all pipelines
npx tsx ~/.claude/skills/concourse/list_pipelines.ts '{}'

# Get pipeline details
npx tsx ~/.claude/skills/concourse/get_pipeline.ts '{"pipeline_name": "my-pipeline"}'

# List jobs in a pipeline
npx tsx ~/.claude/skills/concourse/list_jobs.ts '{"pipeline_name": "my-pipeline"}'

# Trigger a job
npx tsx ~/.claude/skills/concourse/trigger_job.ts '{"pipeline_name": "my-pipeline", "job_name": "build"}'

# Get a build
npx tsx ~/.claude/skills/concourse/get_build.ts '{"build_id": 12345}'

# List recent builds for a job
npx tsx ~/.claude/skills/concourse/list_builds.ts '{"pipeline_name": "my-pipeline", "job_name": "build", "limit": 10}'

# Pause a pipeline
npx tsx ~/.claude/skills/concourse/pause_pipeline.ts '{"pipeline_name": "my-pipeline"}'

# Unpause a pipeline
npx tsx ~/.claude/skills/concourse/unpause_pipeline.ts '{"pipeline_name": "my-pipeline"}'

# Get pipeline config
npx tsx ~/.claude/skills/concourse/get_pipeline_config.ts '{"pipeline_name": "my-pipeline"}'

# List resources
npx tsx ~/.claude/skills/concourse/list_resources.ts '{"pipeline_name": "my-pipeline"}'

# Set pipeline config
npx tsx ~/.claude/skills/concourse/set_pipeline.ts '{"pipeline_name": "my-pipeline", "config": {...}}'
```

## Related Skills

- **`concourse-pipelines`** — Comprehensive pipeline authoring reference. Use when you need guidance on pipeline YAML structure, step types, resources, variables, or best practices.
- **`fly-operations`** — Fly CLI operations reference including worker troubleshooting. Use when running fly commands or diagnosing infrastructure issues.

---
name: fly
description: Concourse CI integration via fly CLI wrapper skills.
---

# Fly CLI Skills (Concourse CI)

REST-style skill wrappers for the [Concourse CI](https://concourse-ci.org/) `fly` CLI tool. These skills follow the same TypeScript pattern as other integration skills (Jira, Bitbucket, etc.) but execute `fly` CLI commands instead of making HTTP requests.

## Prerequisites

- The `fly` CLI must be installed and available on your PATH
- A Concourse CI instance must be accessible
- Credentials must be configured (see Credentials section below)

## Available Skills

| Skill | Description |
|-------|-------------|
| `login` | Login to a Concourse target |
| `list_pipelines` | List all pipelines on the target |
| `get_pipeline` | Get pipeline configuration as JSON |
| `set_pipeline` | Create or update a pipeline from YAML |
| `validate_pipeline` | Validate a pipeline YAML file |
| `trigger_job` | Trigger a job in a pipeline |
| `list_builds` | List recent builds with optional filters |
| `watch_build` | Watch or retrieve build output |
| `abort_build` | Cancel a running build |
| `workers` | List registered workers with state and metadata |
| `land_worker` | Gracefully drain a worker for maintenance |
| `prune_worker` | Remove a stalled worker from the database |
| `containers` | List active containers across workers |

## Credentials

Only `target` and `url` are required. Authentication uses browser-based login (`fly login -b`).

Credentials are resolved in the following order:

### 1. Environment Variables

```bash
export FLY_TARGET=${CI_TARGET}
export CONCOURSE_URL=https://ci.dev.example.com
```

### 2. .env File

Place a `.env` file in your `$PROJECT_ROOT`:

```
FLY_TARGET=${CI_TARGET}
CONCOURSE_URL=https://ci.dev.example.com
```

### 3. settings.json

Add credentials to `~/.claude/settings.json`:

```json
{
  "credentials": {
    "fly": {
      "target": "${TENANT_NAMESPACE}",
      "url": "https://ci.dev.example.com"
    }
  }
}
```

## Usage

All skills follow the standard invocation pattern:

```bash
npx tsx ~/.claude/skills/fly/{skill_name}.ts '{JSON_PARAMS}'
```

### Examples

```bash
# Login to Concourse
npx tsx ~/.claude/skills/fly/login.ts '{}'

# List all pipelines
npx tsx ~/.claude/skills/fly/list_pipelines.ts '{}'

# Get pipeline configuration
npx tsx ~/.claude/skills/fly/get_pipeline.ts '{"pipeline_name": "my-app"}'

# Validate a pipeline YAML
npx tsx ~/.claude/skills/fly/validate_pipeline.ts '{"pipeline_file": "ci/pipeline.yml"}'

# Set a pipeline with variables
npx tsx ~/.claude/skills/fly/set_pipeline.ts '{"pipeline_name": "my-app", "pipeline_file": "ci/pipeline.yml", "vars": {"branch": "main"}}'

# Trigger a job
npx tsx ~/.claude/skills/fly/trigger_job.ts '{"pipeline_name": "my-app", "job_name": "build"}'

# List recent builds for a pipeline
npx tsx ~/.claude/skills/fly/list_builds.ts '{"pipeline": "my-app", "count": 10}'

# Watch a build
npx tsx ~/.claude/skills/fly/watch_build.ts '{"build_id": 42}'
```

## Architecture

Unlike other skills that call REST APIs directly, these skills wrap the `fly` CLI:

```
Skill Script (.ts)
  --> fly-client.ts (credential loading, login management)
    --> child_process.execSync (fly CLI execution)
      --> Concourse CI Server
```

The `fly-client.ts` shared module provides:

- **Credential loading** from env vars, `.env`, or `settings.json`
- **Automatic login** when the target session has expired
- **`flyExec(args)`** - Execute fly commands and return stdout
- **`flyExecJson<T>(args)`** - Execute fly commands with `--json` and parse the response
- **`getFlyTarget()`** - Get the configured target name

## Auto-Login

Skills automatically check if the fly CLI is logged in to the target before executing commands. If the session has expired, a browser-based login (`fly login -b`) is triggered automatically. If a command fails mid-execution due to a token expiry, the client will re-authenticate and retry the command once. This means you rarely need to call the `login` skill explicitly.

## Notes

- All commands are executed synchronously with a 120-second timeout
- JSON output is automatically requested where supported via the `--json` flag
- The `set_pipeline` skill uses `--non-interactive` to skip confirmation prompts
- Build output from `watch_build` and `trigger_job --watch` can be large; the max buffer is 10MB

## Related Skills

- **`fly-operations`** — Comprehensive fly CLI operations reference including worker troubleshooting. Use when you need guidance on which fly commands to run or how to diagnose stuck workers.
- **`concourse-pipelines`** — Pipeline authoring reference. Use when writing or reviewing Concourse pipeline YAML.

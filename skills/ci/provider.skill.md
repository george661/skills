# Unified CI/CD Skills

Unified interface for CI/CD operations across Concourse, GitHub Actions, and CircleCI. Each skill resolves the provider, translates parameters to provider-native format, and delegates to the corresponding backend skill.

## How It Works

```
ci/get_build_status.ts  ──►  ci-router.ts  ──►  concourse/get_build.ts
                                   │              fly/trigger_job.ts
                                   │              fly/watch_build.ts
                                   │                    OR
                                   └──────►  github-actions/get_workflow_run.ts
                                              github-actions/trigger_workflow.ts
                                              github-actions/get_run_logs.ts
```

## Provider Resolution

Resolution order (first match wins):

1. Explicit `provider` parameter on the call
2. `CI_PROVIDER` environment variable
3. Default: `concourse`

### Environment Variable

```bash
export CI_PROVIDER=concourse       # Concourse CI (default)
export CI_PROVIDER=github_actions  # GitHub Actions
export CI_PROVIDER=circleci        # CircleCI (stub)
```

## Skill Mapping

| Unified Skill | Concourse Backend | GitHub Actions Backend |
|---------------|-------------------|------------------------|
| `get_build_status` | `concourse/get_build` | `github-actions/get_workflow_run` |
| `trigger_build` | `fly/trigger_job` | `github-actions/trigger_workflow` |
| `get_build_logs` | `fly/watch_build` | `github-actions/get_run_logs` |
| `list_builds` | `concourse/list_builds` | `github-actions/list_workflow_runs` |

## Parameter Translation

| Unified Param | Concourse | GitHub Actions |
|--------------|-----------|----------------|
| `repo` | `pipeline` | `repo` (+ `owner` from `GITHUB_OWNER` env) |
| `run_id` | passthrough | passthrough |
| `build_id` | passthrough | passthrough |
| `job` | passthrough | passthrough |
| `workflow_id` | passthrough | passthrough |
| `ref` | passthrough | passthrough |
| `branch` | passthrough | passthrough |
| `status` | passthrough | passthrough |

## Skills

| Skill | Description | Required Params | Optional Params |
|-------|-------------|-----------------|-----------------|
| `get_build_status` | Get status of a build/run | `repo` | `run_id`, `build_id`, `provider` |
| `list_builds` | List recent builds/runs | `repo` | `branch`, `status`, `provider` |
| `trigger_build` | Trigger a new build/run | `repo` | `job`, `workflow_id`, `ref`, `provider` |
| `get_build_logs` | Get build/run logs | `repo` | `run_id`, `build_id`, `provider` |

## Example Invocations

### Concourse (default)

```bash
npx tsx skills/ci/get_build_status.ts '{"repo": "my-api"}'
npx tsx skills/ci/list_builds.ts '{"repo": "my-api"}'
npx tsx skills/ci/trigger_build.ts '{"repo": "my-api", "job": "test"}'
npx tsx skills/ci/get_build_logs.ts '{"repo": "my-api", "build_id": "456"}'
```

### GitHub Actions

```bash
npx tsx skills/ci/get_build_status.ts '{"repo": "my-api", "run_id": "12345", "provider": "github_actions"}'
npx tsx skills/ci/list_builds.ts '{"repo": "my-api", "provider": "github_actions"}'
npx tsx skills/ci/trigger_build.ts '{"repo": "my-api", "workflow_id": "ci.yml", "ref": "main", "provider": "github_actions"}'
npx tsx skills/ci/get_build_logs.ts '{"repo": "my-api", "run_id": "12345", "provider": "github_actions"}'
```

## CI in PR Context vs Standalone

- **PR-context CI**: Use `skills/vcs/wait_for_ci.ts` and `skills/vcs/get_ci_logs.ts` — these are aware of the PR branch and provider context from the VCS router.
- **Standalone CI ops**: Use these `skills/ci/` skills — for direct pipeline/workflow management outside of PR workflows.

## Debugging

Set `CI_DEBUG=1` to enable verbose logging from the router:

```bash
CI_DEBUG=1 npx tsx skills/ci/get_build_status.ts '{"repo": "my-api"}'
```

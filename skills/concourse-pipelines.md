---
name: concourse-pipelines
description: Concourse CI pipeline authoring reference. Use when writing, reviewing, or debugging pipeline YAML.
---

# Concourse CI Pipeline Authoring Reference

This skill provides a complete reference for authoring Concourse CI pipeline YAML, grounded in the official Concourse documentation.

## 1. Pipeline Structure

A pipeline is a YAML file with the following top-level keys:

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `jobs` | `[job]` | Yes | Set of jobs for the pipeline to continuously schedule. At least one job is required. |
| `resources` | `[resource]` | No | Resources the pipeline continuously monitors for new versions. |
| `resource_types` | `[resource_type]` | No | Custom resource type definitions. Can override core types by matching names. |
| `var_sources` | `[var_source]` | No | Pipeline-level variable source configurations. |
| `groups` | `[group_config]` | No | Organize jobs into UI tabs. No functional effect on pipeline behavior. |
| `display` | `display_config` | No | Visual customization (experimental, v6.6.0+). |

### Identifiers

Pipeline and resource names follow the `identifier` schema: lowercase Unicode letters, numbers, hyphens, underscores, and periods. Must start with a lowercase letter or number.

### Groups

Groups organize jobs into navigable tabs in the web UI.

```yaml
groups:
  - name: deploy
    jobs:
      - build
      - deploy-*
  - name: tests
    jobs:
      - unit-tests
      - "{integration,e2e}-*"
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | `identifier` | Unique name used as the tab label. |
| `jobs` | `[job.name]` | List of job references. Supports glob patterns (`*`, `{a,b}`). Jobs may appear in multiple groups. |

**Rule:** Once you add groups to a pipeline, ALL jobs must belong to at least one group. Jobs not in any group become invisible in the UI.

### Display

```yaml
display:
  background_image: https://example.com/bg.png
  background_filter: "opacity(30%) grayscale(100%)"
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `background_image` | `string` | none | HTTP, HTTPS, or relative URL for the pipeline background image. |
| `background_filter` | `string` | `opacity(30%) grayscale(100%)` | CSS filter rules applied to the background image. |

## 2. Jobs

A job describes a sequence of steps to execute. Builds are created either by `trigger: true` on a `get` step or by manual invocation.

### Job Schema

```yaml
jobs:
  - name: run-tests
    serial: true
    serial_groups: [deploy]
    max_in_flight: 1
    interruptible: false
    public: false
    disable_manual_trigger: false
    old_name: legacy-test-job
    build_log_retention:
      days: 30
      builds: 100
      minimum_succeeded_builds: 5
    plan:
      - get: source-code
        trigger: true
      - task: unit-tests
        file: source-code/ci/unit.yml
    on_success:
      put: notify
      params: { message: "Tests passed" }
    on_failure:
      put: notify
      params: { message: "Tests failed" }
    ensure:
      put: cleanup
```

### All Job Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `identifier` | **required** | Short name displayed in URLs and the web UI. |
| `plan` / `steps` | `[step]` | **required** | Sequence of steps to execute. |
| `serial` | `bool` | `false` | When true, builds queue and execute one at a time instead of in parallel. |
| `serial_groups` | `[identifier]` | `[]` | Tag-based serialization across jobs. Builds of jobs sharing the same tag serialize with each other. |
| `max_in_flight` | `number` | unlimited | Maximum concurrent builds. Overridden if `serial` or `serial_groups` are set. |
| `interruptible` | `bool` | `false` | When true, workers will not wait for running builds of this job during shutdown. Use for long-running, low-importance jobs. |
| `public` | `bool` | `false` | When true, build logs are viewable by unauthenticated users. |
| `disable_manual_trigger` | `bool` | `false` | When true, prevents manual triggering via UI or `fly trigger-job`. |
| `old_name` | `identifier` | none | Preserves build history when renaming a job. Set to the previous name. |
| `build_log_retention` | `object` | none | Controls log retention policy (see sub-fields below). |

**`build_log_retention` sub-fields:**

| Field | Type | Description |
|-------|------|-------------|
| `days` | `number` | Keep logs from builds completed within this many days. |
| `builds` | `number` | Retain logs from the last N builds. |
| `minimum_succeeded_builds` | `number` | Preserve at least this many successful build logs. Requires `builds` > 0. |

### Job Hooks

Hooks are steps that run conditionally based on the outcome of the job plan. See Section 4 for full hook/modifier details.

```yaml
jobs:
  - name: deploy
    plan:
      - get: app
      - task: deploy-app
        file: app/ci/deploy.yml
    on_success: { put: slack, params: { text: "Deploy succeeded" } }
    on_failure: { put: slack, params: { text: "Deploy failed" } }
    on_error: { put: slack, params: { text: "Deploy errored" } }
    on_abort: { put: slack, params: { text: "Deploy aborted" } }
    ensure: { task: cleanup, file: app/ci/cleanup.yml }
```

## 3. Step Types

Steps execute sequentially within a job plan. If any step fails, subsequent steps do not execute (unless wrapped in `try` or modified by hooks).

### `get` -- Fetch a Resource

Fetches a version of a resource and places it as an artifact in the build.

```yaml
- get: source-code
  resource: my-repo
  trigger: true
  passed: [build, test]
  version: latest
  params:
    depth: 1
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `get` | `resource.name` or `identifier` | **required** | Resource to fetch. Also serves as the artifact name unless `resource` is specified. |
| `resource` | `resource.name` | same as `get` | Override the pipeline resource name (allows renaming within a job). |
| `passed` | `[job.name]` | none | Only use versions that passed through ALL listed jobs. Implements fan-in with AND logic. |
| `trigger` | `bool` | `false` | When true, new versions automatically create builds for this job. |
| `version` | `latest` / `every` / `{key: value}` | `latest` | Version selection strategy. |
| `params` | `config` | none | Arbitrary configuration passed to the resource type's `get` operation. |

**Key behaviors:**

- `trigger: true` -- Automatically creates builds when new versions appear. If no get step has trigger enabled, the job must be triggered manually.
- `passed: [job-a, job-b]` -- Implements fan-in. Only versions that successfully passed through ALL listed jobs are eligible. This is the primary mechanism for promoting artifacts through a pipeline.
- `version: latest` -- Uses the most recent version, potentially skipping intermediates.
- `version: every` -- Processes every version sequentially, never skipping.
- `version: {ref: abc123}` -- Pins to a specific version. The version must have been detected by a check; use `fly check-resource` to register historical versions.

### `put` -- Push to a Resource

Pushes data to a resource. On success, the resulting version is implicitly fetched via an automatic `get` step.

```yaml
- put: deploy-artifact
  resource: s3-bucket
  inputs: detect
  params:
    file: build-output/app-*.tar.gz
  get_params:
    skip_download: true
  no_get: false
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `put` | `resource.name` or `identifier` | **required** | Resource to push to. Also serves as the artifact name. |
| `resource` | `resource.name` | same as `put` | Override the pipeline resource name. |
| `inputs` | `detect` / `all` / `[identifier]` | `detect` | Controls which artifacts are streamed to the container. |
| `params` | `config` | none | Arbitrary configuration for the resource's `put` operation. |
| `get_params` | `config` | none | Configuration passed to the implicit `get` step that follows a successful put. |
| `no_get` | `bool` | `false` | Skips the implicit get step. Use when no subsequent steps need the resulting artifact. |

**Key behaviors:**

- **Implicit get** -- After a successful put, Concourse automatically runs a get to fetch the resulting version. This artifact becomes available to subsequent steps under the `put` identifier.
- `inputs: detect` -- Automatically detects required artifacts by scanning string values in `params` and using the first path segment as an identifier. This is the most common and recommended setting.
- `inputs: all` -- Streams all artifacts. May impact performance with large artifacts.
- `inputs: [name-a, name-b]` -- Explicitly lists which artifacts to provide. Use for precision.
- `no_get: true` -- Skip the implicit get. Use on terminal puts (e.g., notifications) where no downstream step needs the result.

### `task` -- Run Code

Executes a script in a container. Tasks are pure functions: given inputs, they produce outputs.

```yaml
- task: run-unit-tests
  file: source-code/ci/tasks/unit.yml
  image: custom-image
  privileged: false
  vars:
    env: staging
  params:
    DEBUG: "true"
  input_mapping:
    source: source-code
  output_mapping:
    results: test-results
  container_limits:
    cpu: 1024
    memory: 1073741824
  hermetic: false
```

**Step-level fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `task` | `identifier` | **required** | Display name in the web UI. |
| `file` | `file-path` | none | Path to external `.yml` task config file. Supports `((vars))` interpolation. Preferred over `config`. |
| `config` | `task-config` | none | Inline task configuration. Use `file` instead for reusability. |
| `image` | `identifier` | none | Artifact name containing a rootfs image. Overrides `image_resource` in the task config. |
| `privileged` | `bool` | `false` | Grants escalated container capabilities. Security risk. |
| `vars` | `{string: value}` | none | Template variables interpolated into the external task file. Different from `params`. |
| `params` | `{string: string}` | none | Environment variable overrides. Merged with task config params. |
| `container_limits` | `object` | none | CPU and memory constraints for the task container. |
| `hermetic` | `bool` | `false` | Disables outbound network access. Linux containerd runtime only. |
| `input_mapping` | `{task-input: plan-artifact}` | none | Maps generic task input names to specific plan artifact names. Enables task reuse. |
| `output_mapping` | `{task-output: plan-name}` | none | Maps task output names to plan-level artifact names. |

**Task config fields** (used in `file` or `config`):

| Field | Type | Description |
|-------|------|-------------|
| `platform` | `string` | **Required.** Target platform: `linux`, `darwin`, or `windows`. |
| `image_resource` | `{type, source}` | Container image specification. Usually `type: registry-image`. |
| `inputs` | `[{name, path?, optional?}]` | Named input artifacts the task expects. |
| `outputs` | `[{name, path?}]` | Named output artifacts the task produces. Registered in the build's artifact namespace. |
| `caches` | `[{path}]` | Paths to cache between builds on the same worker. |
| `params` | `{KEY: value}` | Default environment variables. Set value to empty string to require override. |
| `run` | `{path, args?, dir?, user?}` | **Required.** Command to execute. |

**Example external task file** (`ci/tasks/unit.yml`):

```yaml
platform: linux

image_resource:
  type: registry-image
  source:
    repository: golang
    tag: "1.21"

inputs:
  - name: source

outputs:
  - name: coverage

caches:
  - path: go-cache

params:
  GOCACHE: go-cache
  CGO_ENABLED: "0"

run:
  path: sh
  args:
    - -exc
    - |
      cd source
      go test -coverprofile=../coverage/coverage.out ./...
```

### `set_pipeline` -- Configure a Pipeline

Sets or updates a pipeline configuration from within a build.

```yaml
- set_pipeline: my-app
  file: source-code/ci/pipeline.yml
  vars:
    env: staging
  var_files:
    - source-code/ci/vars/staging.yml
  instance_vars:
    branch: feature-x
  team: my-team
```

**Self-updating pattern:**

```yaml
- set_pipeline: self
  file: source-code/ci/pipeline.yml
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `set_pipeline` | `identifier` or `self` | **required** | Pipeline name to configure. `self` updates the current pipeline. |
| `file` | `file-path` | **required** | Path to the pipeline YAML file. First segment must reference a plan artifact. |
| `vars` | `{string: value}` | none | Template variables for pipeline interpolation. |
| `var_files` | `[file-path]` | none | YAML files containing variables. Later files override earlier ones. Equivalent to `--load-vars-from`. |
| `instance_vars` | `{string: value}` | none | Instance variables identifying instanced pipelines. Also interpolated into the pipeline config. |
| `team` | `identifier` | current team | Team that owns the pipeline. Only the `main` team can set another team's pipeline. |

**Key behaviors:**

- Pipelines created by `set_pipeline` start **unpaused** (unless `team` specifies another team).
- **Auto-archiving:** Pipelines are automatically archived when the job that set them removes the `set_pipeline` step, the job itself is removed, or its parent pipeline is destroyed.
- `set_pipeline: self` enables a pipeline to update its own configuration, eliminating manual `fly set-pipeline` commands.

### `in_parallel` -- Run Steps Concurrently

Executes multiple steps in parallel.

**Shorthand (array form):**

```yaml
- in_parallel:
    - get: resource-a
    - get: resource-b
    - get: resource-c
```

**Full form (with options):**

```yaml
- in_parallel:
    steps:
      - get: resource-a
      - get: resource-b
      - get: resource-c
    limit: 2
    fail_fast: true
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `steps` | `[step]` | **required** | Steps to execute concurrently. |
| `limit` | `number` | unlimited | Maximum concurrent steps (semaphore). When unset, all steps start immediately. |
| `fail_fast` | `bool` | `false` | When true, returns immediately on first sub-step failure, stopping running steps and canceling pending ones. |

**Key behaviors:**

- Accepts either a direct array of steps (shorthand) or a config object with `steps`, `limit`, and `fail_fast`.
- If any sub-step fails or errors, the entire parallel step fails or errors. All steps continue executing unless `fail_fast: true`.

### `load_var` -- Create a Build-Scoped Variable

Reads a file and creates a local variable accessible to subsequent steps.

```yaml
- load_var: version
  file: version-file/version
  format: trim
  reveal: true
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `load_var` | `identifier` | **required** | Variable name. Accessible as `((.:name))` in subsequent steps. |
| `file` | `file-path` | **required** | Path to the file whose content becomes the variable value. |
| `format` | `json` / `yaml` / `yml` / `trim` / `raw` | auto-detect from extension | How to parse the file content. `trim` strips whitespace. `raw` preserves content as-is. |
| `reveal` | `bool` | `false` | When true, the variable value appears in build output despite secret redaction. |

**Variable access syntax:**

- Simple value: `((.:version))`
- Nested field: `((.:config.database.host))`

### `do` -- Serial Step Group

Executes steps serially with the same semantics as a top-level plan. Primarily used inside `try`, `across`, or hooks to group multiple steps.

```yaml
- try:
    do:
      - get: optional-resource
      - task: optional-processing
        file: optional-resource/ci/process.yml
```

| Field | Type | Description |
|-------|------|-------------|
| `do` | `[step]` | **required.** Steps to execute serially. |

### `try` -- Ignore Failure

Executes the given step and masks any failure as success. Use for non-critical side effects.

```yaml
- task: run-tests
  file: source/ci/test.yml
  on_success:
    try:
      put: test-logs
      params:
        from: run-tests/*.log
```

| Field | Type | Description |
|-------|------|-------------|
| `try` | `step` | **required.** The step to execute. Failure is masked as success. |

## 4. Hooks and Modifiers

Hooks and modifiers attach to any step to control behavior on completion, failure, or other conditions.

### Hooks

| Hook | Type | Trigger Condition | Recovers Parent? |
|------|------|-------------------|------------------|
| `on_success` | `step` | Parent step succeeds. | N/A |
| `on_failure` | `step` | Parent step fails. | **No.** The overall step still fails even if the hook succeeds. |
| `on_error` | `step` | Parent step terminates abnormally (config errors, network issues, timeout expiry). Not triggered by normal failure or abort. | No |
| `on_abort` | `step` | Build is aborted while the parent step was running. | No |
| `ensure` | `step` | **Always.** Runs after the parent step regardless of success, failure, error, or abort. | No. If parent succeeds but ensure fails, the overall step fails. |

**Execution order:** `on_success`/`on_failure`/`on_error`/`on_abort` runs first (whichever matches), then `ensure` runs unconditionally.

### Modifiers

| Modifier | Type | Default | Description |
|----------|------|---------|-------------|
| `timeout` | `duration` | none | Maximum time a step may execute. Uses Go `time.ParseDuration` format (`30s`, `5m`, `1h30m`). Exceeded timeout results in `errored` status (not `aborted`). |
| `attempts` | `number` | 1 | Total times to run the step before failing. Retries on both failure and error. When combined with `timeout`, the timeout applies **per attempt**, not to the total. |
| `tags` | `[string]` | `[]` | Restricts step execution to workers matching all specified tags. |

**Example combining hooks and modifiers:**

```yaml
- task: integration-tests
  file: source/ci/integration.yml
  timeout: 30m
  attempts: 3
  on_failure:
    put: slack
    params: { text: "Integration tests failed after 3 attempts" }
  ensure:
    task: teardown
    file: source/ci/teardown.yml
```

## 5. Resources

Resources represent external versioned artifacts that a pipeline monitors and interacts with.

### Resource Schema

```yaml
resources:
  - name: source-code
    type: git
    icon: github
    check_every: 2m
    check_timeout: 5m
    webhook_token: ((webhook-token))
    source:
      uri: git@github.com:org/repo.git
      branch: main
      private_key: ((deploy-key))
    tags: [private-network]
    public: false
    expose_build_created_by: false
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `identifier` | **required** | Short name referenced by get/put steps. |
| `type` | `resource_type.name` | **required** | Resource type implementation to use. |
| `source` | `config` | **required** | Resource-specific configuration passed to the resource type. |
| `icon` | `string` | none | Material Design icon name displayed in the web UI. |
| `check_every` | `duration` or `"never"` | `1m` | Interval for checking new versions. Set to `"never"` to disable automatic checks. |
| `check_timeout` | `duration` | `1h` | Maximum time allowed for a version check. |
| `webhook_token` | `string` | none | Enables HTTP webhooks to trigger immediate resource checks. |
| `old_name` | `identifier` | none | Preserves version history when renaming a resource. |
| `version` | `{key: value}` | none | Pins the resource to a specific version across the entire pipeline. |
| `tags` | `[string]` | `[]` | Worker tags determining which nodes perform resource checks. |
| `public` | `bool` | `false` | Exposes version metadata to unauthenticated users. |
| `expose_build_created_by` | `bool` | `false` | Makes `BUILD_CREATED_BY` metadata available during put steps. |

### Core Resource Types

#### `git`

```yaml
resources:
  - name: repo
    type: git
    icon: github
    source:
      uri: git@github.com:org/repo.git
      branch: main
      private_key: ((deploy-key))
      paths: ["src/**", "ci/**"]
      ignore_paths: ["docs/**"]
      git_config:
        - name: core.bigFileThreshold
          value: 10m
```

Key `source` fields: `uri` (required), `branch`, `private_key`, `username`, `password`, `paths` (glob triggers), `ignore_paths`, `tag_filter`, `tag_regex`, `fetch_tags`, `skip_ssl_verification`, `git_config`, `commit_filter`, `version_depth`.

Key `get` params: `depth` (shallow clone), `submodules`, `disable_git_lfs`, `fetch_tags`.

Key `put` params: `repository` (required), `rebase`, `tag`, `tag_prefix`, `force`, `branch`, `notes`, `merge`.

#### `registry-image`

```yaml
resources:
  - name: app-image
    type: registry-image
    icon: docker
    source:
      repository: myorg/myapp
      tag: latest
      username: ((docker-username))
      password: ((docker-password))
```

Key `source` fields: `repository` (required), `tag` (default: `latest`), `tag_regex`, `username`, `password`, `aws_access_key_id`, `aws_secret_access_key`, `aws_region` (for ECR), `insecure`, `ca_certs`, `semver_constraint`, `variant`, `platform`.

#### `s3`

```yaml
resources:
  - name: release-tarball
    type: s3
    icon: aws
    source:
      bucket: my-releases
      regexp: releases/app-(.*).tar.gz
      access_key_id: ((aws-access-key))
      secret_access_key: ((aws-secret-key))
      region_name: us-east-1
```

Key `source` fields: `bucket` (required), `regexp` or `versioned_file` (one required), `access_key_id`, `secret_access_key`, `region_name` (default: `us-east-1`), `endpoint`, `disable_ssl`, `server_side_encryption`, `sse_kms_key_id`.

#### `time`

```yaml
resources:
  - name: nightly
    type: time
    icon: clock-outline
    source:
      interval: 24h
      location: America/New_York
      start: "2:00 AM"
      stop: "3:00 AM"
      days: [Monday, Tuesday, Wednesday, Thursday, Friday]
```

Key `source` fields: `interval` (Go duration; if omitted, one version per day), `location` (IANA timezone, default: UTC), `start`/`stop` (time window; must be specified together), `days` (weekday filter), `initial_version` (bool).

## 6. Custom Resource Types

Define custom resource types to extend pipeline capabilities beyond the core types.

```yaml
resource_types:
  - name: slack-notification
    type: registry-image
    source:
      repository: cfcommunity/slack-notification-resource
      tag: latest
    defaults:
      url: ((slack-webhook-url))

  - name: pull-request
    type: registry-image
    source:
      repository: teliaoss/github-pr-resource
    check_every: 1m
    tags: [public-network]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `identifier` | **required** | Name referenced by resources using this type. |
| `type` | `resource_type.name` | **required** | Type providing the container image (usually `registry-image`). |
| `source` | `config` | **required** | Configuration for fetching the resource type image. |
| `privileged` | `bool` | `false` | Grants full container capabilities. Document why when enabled. |
| `params` | `config` | none | Configuration passed when running the get step for the resource type image. |
| `check_every` | `duration` | `1m` | How often to check for new versions of the resource type image. Go `ParseDuration` format. |
| `tags` | `[string]` | `[]` | Worker selection tags for running this resource type. |
| `defaults` | `config` | none | Default source config merged into all resources of this type. Resource-level values take precedence. |

**Key behaviors:**

- Custom resource types can **override core types** (git, registry-image, s3, time) by using the same name.
- A resource type's `type` can reference another custom resource type, enabling version-pinning of resource type images.
- `defaults` are merged with each resource's `source` at runtime. Use for shared configuration like credentials or endpoints.

## 7. Variables and Secrets

### Syntax

Full variable reference syntax:

```
((source-name:secret-path.secret-field))
```

| Component | Required | Description |
|-----------|----------|-------------|
| `source-name` | No | Var source name. Omit for cluster-wide credential manager or static vars. |
| `secret-path` | Yes | Location of the credential. Interpretation varies by source type. |
| `secret-field` | No | Specific field within the fetched secret. |

**Local variables** from `load_var` use the `.` prefix:

```yaml
- load_var: version
  file: version-file/number
- task: build
  params:
    VERSION: ((.:version))
```

### Structural Substitution

Variables are substituted **structurally**, not as text replacement. A variable can resolve to any YAML type (string, number, boolean, object, array), preventing broken YAML syntax.

```yaml
# Variable resolving to an object
source: ((aws-creds))
# Equivalent to:
source:
  access_key_id: AKIA...
  secret_access_key: wJal...
```

### Resolution Timing

Variables are fetched as late as possible -- when the step using them is about to execute. This supports short-lived credentials and rapid rotation.

### Static Variables (CLI)

| Flag | Type | Example |
|------|------|---------|
| `-v NAME=VALUE` | String | `-v branch=main` |
| `-y NAME=VALUE` | YAML-parsed | `-y count=42` or `-y enabled=true` |
| `-l FILE` | Load from YAML file | `-l vars/staging.yml` |

### Var Sources

Configure in the pipeline top-level `var_sources` or at the cluster level.

| Type | Purpose |
|------|---------|
| `vault` | HashiCorp Vault integration. Key fields: `url`, `path_prefix` (default: `/concourse`), `auth_backend`, `client_token`, `ca_cert`. |
| `ssm` | AWS Systems Manager Parameter Store. |
| `secretsmanager` | AWS Secrets Manager. |
| `dummy` | Static credential mapping for testing. |
| `idtoken` | JWT token generation for OIDC-based authentication. |

**Pipeline-level var source example:**

```yaml
var_sources:
  - name: vault
    type: vault
    config:
      url: https://vault.example.com
      path_prefix: /concourse/team
      auth_backend: approle
      auth_params:
        role_id: ((role-id))
        secret_id: ((secret-id))
```

### Dynamic Interpolation Scope

Dynamically resolved vars can parameterize: resource and resource type sources, webhook tokens, task step parameters, complete task configurations, and `set_pipeline` identifiers.

## 8. Best Practices

These recommendations are derived from official Concourse documentation and established patterns.

### Pipeline Design

| Practice | Rationale |
|----------|-----------|
| **Tasks are pure functions.** Define clear inputs and outputs. | Reproducibility and testability. A task given the same inputs should produce the same outputs. |
| **Use external task configs** (`file:` not `config:`). | Reusability, version control, and separation of concerns. Inline configs cannot be shared across jobs. |
| **Never hardcode secrets.** Use `((vars))` for all credentials. | Security. Secrets should come from a credential manager, not pipeline YAML. |
| **Use `passed` constraints for artifact progression.** | Ensures artifacts are promoted through pipeline stages (build -> test -> deploy) with confidence. |
| **Use `in_parallel` for independent gets.** | Reduces build time by fetching resources concurrently. |
| **Use `ensure` for cleanup.** | Guarantees cleanup steps (releasing locks, tearing down infra) run regardless of build outcome. |
| **Combine `timeout` + `attempts` for flaky operations.** | Timeout applies per attempt, preventing a single hung attempt from consuming all retries. |
| **Use `no_get: true` on terminal puts.** | Skips the unnecessary implicit get on puts where no downstream step needs the result (e.g., notifications). |
| **Use `serial_groups` for same-environment deploys.** | Prevents concurrent deploys to the same environment across different jobs. |
| **Validate pipelines before deploying.** | Use `fly validate-pipeline` to catch YAML errors before `fly set-pipeline`. |
| **Use YAML anchors for repeated config.** | Reduces duplication and maintenance burden for shared configuration blocks. |
| **Quote time-like values.** | YAML interprets bare `1:30` as sexagesimal (90). Always quote: `"1:30"` or use `1h30m`. |

### YAML Anchors Example

```yaml
common-task-config: &common-task
  platform: linux
  image_resource:
    type: registry-image
    source:
      repository: golang
      tag: "1.21"

jobs:
  - name: unit
    plan:
      - get: source
        trigger: true
      - task: test
        config:
          <<: *common-task
          inputs: [{ name: source }]
          run:
            path: sh
            args: ["-c", "cd source && go test ./..."]

  - name: lint
    plan:
      - get: source
        trigger: true
      - task: lint
        config:
          <<: *common-task
          inputs: [{ name: source }]
          run:
            path: sh
            args: ["-c", "cd source && golangci-lint run"]
```

### Anti-Patterns

| Anti-Pattern | Correction |
|-------------|------------|
| Inline task configs everywhere | Extract to external YAML files referenced via `file:`. |
| Hardcoded credentials in source | Use `((variable))` syntax with a credential manager. |
| Missing `passed` constraints | Add `passed` to get steps to enforce promotion gates. |
| Using `inputs: all` by default | Use `inputs: detect` (default) or explicit lists. Only use `all` when needed. |
| Ignoring the implicit get after put | Set `no_get: true` when the artifact is not needed downstream. |
| Sequential independent gets | Wrap in `in_parallel` to reduce build time. |

## 9. Executable Skills Reference

The following TypeScript skills provide programmatic access to Concourse and Fly operations. Run from the project root.

### Concourse API Skills (`concourse/`)

| Skill | Description |
|-------|-------------|
| `get_build` | Retrieve details of a specific build. |
| `get_pipeline` | Retrieve pipeline metadata. |
| `get_pipeline_config` | Retrieve the YAML configuration of a pipeline. |
| `list_builds` | List builds with optional filtering. |
| `list_jobs` | List jobs in a pipeline. |
| `list_pipelines` | List all pipelines for a team. |
| `list_resources` | List resources in a pipeline. |
| `pause_pipeline` | Pause a pipeline. |
| `set_pipeline` | Set or update a pipeline configuration. |
| `trigger_job` | Trigger a job build. |
| `unpause_pipeline` | Unpause a pipeline. |

### Fly CLI Skills (`fly/`)

| Skill | Description |
|-------|-------------|
| `get_pipeline` | Get pipeline config via fly CLI. |
| `list_builds` | List builds via fly CLI. |
| `list_pipelines` | List pipelines via fly CLI. |
| `login` | Authenticate to a Concourse target. |
| `set_pipeline` | Set pipeline config via fly CLI. |
| `trigger_job` | Trigger a job via fly CLI. |
| `validate_pipeline` | Validate pipeline YAML without deploying. |
| `watch_build` | Stream build output in real time. |

**Usage:** `npx tsx .claude/skills/concourse/{skill}.ts '{...params}'`

For fly CLI commands to set, validate, and format pipelines, see the `fly/` skills directory and its `README.md`.

## 10. Documentation Source

All content in this skill is grounded in the official Concourse CI documentation:

- **Repository:** https://github.com/concourse/docs
- **Published site:** https://concourse-ci.org/docs/
- **Pipeline schema:** `docs/docs/pipelines/` -- top-level keys, groups, display
- **Job schema:** `docs/docs/jobs.md` -- job fields, build log retention
- **Step types:** `docs/docs/steps/` -- get, put, task, set-pipeline, in-parallel, load-var, do, try
- **Hooks and modifiers:** `docs/docs/steps/modifier-and-hooks/` -- on_success, on_failure, on_error, on_abort, ensure, timeout, attempts, tags, across
- **Resources:** `docs/docs/resources/` -- resource schema, core types
- **Resource types:** `docs/docs/resource-types/` -- custom resource type schema
- **Variables:** `docs/docs/vars.md` -- variable syntax, var sources, static vars
- **Config basics:** `docs/docs/config-basics.md` -- identifier schema, duration format, YAML conventions
- **Core resource type repos:**
  - git: https://github.com/concourse/git-resource
  - registry-image: https://github.com/concourse/registry-image-resource
  - s3: https://github.com/concourse/s3-resource
  - time: https://github.com/concourse/time-resource

---
name: fly-operations
description: Fly CLI operations reference including worker troubleshooting. Use when running fly commands, diagnosing stuck workers, or managing Concourse infrastructure.
---

# Fly CLI Operations Reference

Complete reference for the Concourse CI `fly` CLI, worker lifecycle management, and troubleshooting procedures. Grounded in official Concourse documentation and source code.

## Command Quick Reference

Every registered fly command with its alias (from `fly/commands/fly.go`):

| Command | Alias | Description |
|---------|-------|-------------|
| `login` | `l` | Authenticate with the target |
| `logout` | `o` | Release authentication with the target |
| `targets` | `ts` | List saved targets |
| `delete-target` | `dtg` | Delete target |
| `edit-target` | `etg` | Edit a target |
| `status` | -- | Login status |
| `sync` | `s` | Download and replace the current fly from the target |
| `userinfo` | -- | User information |
| `active-users` | `au` | List the active users since a date or for the past 2 months |
| `teams` | `t` | List the configured teams |
| `get-team` | `gt` | Show team configuration |
| `set-team` | `st` | Create or modify a team to have the given credentials |
| `rename-team` | `rt` | Rename a team |
| `destroy-team` | `dt` | Destroy a team and delete all of its data |
| `pipelines` | `ps` | List the configured pipelines |
| `paused-pipelines` | `pps` | List the configured paused pipelines |
| `set-pipeline` | `sp` | Create or update a pipeline's configuration |
| `get-pipeline` | `gp` | Get a pipeline's current configuration |
| `destroy-pipeline` | `dp` | Destroy a pipeline |
| `pause-pipeline` | `pp` | Pause a pipeline |
| `unpause-pipeline` | `up` | Un-pause a pipeline |
| `archive-pipeline` | `ap` | Archive a pipeline |
| `expose-pipeline` | `ep` | Make a pipeline publicly viewable |
| `hide-pipeline` | `hp` | Hide a pipeline from the public |
| `rename-pipeline` | `rp` | Rename a pipeline |
| `validate-pipeline` | `vp` | Validate a pipeline config |
| `format-pipeline` | `fp` | Format a pipeline config |
| `order-pipelines` | `op` | Orders pipelines |
| `order-instanced-pipelines` | `oip` | Orders instanced pipelines within an instance group |
| `checklist` | `cl` | Print a Checkfile of the given pipeline |
| `jobs` | `js` | List the jobs in the pipelines |
| `paused-jobs` | `pjs` | List the paused jobs in the pipelines |
| `trigger-job` | `tj` | Start a job in a pipeline |
| `pause-job` | `pj` | Pause a job |
| `unpause-job` | `uj` | Unpause a job |
| `schedule-job` | `sj` | Request the scheduler to run for a job |
| `builds` | `bs` | List builds data |
| `watch` | `w` | Stream a build's output |
| `abort-build` | `ab` | Abort a build |
| `rerun-build` | `rb` | Rerun a build |
| `execute` | `e` | Execute a one-off build using local bits |
| `hijack` / `intercept` | `i` | Execute a command in a container |
| `resources` | `rs` | List the resources in the pipeline |
| `resource-versions` | `rvs` | List the versions of a resource |
| `check-resource` | `cr` | Check a resource |
| `check-resource-type` | `crt` | Check a resource-type |
| `pin-resource` | `pr` | Pin a version to a resource |
| `unpin-resource` | `ur` | Unpin a resource |
| `enable-resource-version` | `erv` | Enable a version of a resource |
| `disable-resource-version` | `drv` | Disable a version of a resource |
| `clear-resource-cache` | `crc` | Clear cache of a resource |
| `clear-task-cache` | `ctc` | Clears cache from a task container |
| `clear-versions` | `cv` | Clear versions of a resource or resource type |
| `workers` | `ws` | List the registered workers |
| `land-worker` | `lw` | Land a worker |
| `prune-worker` | `pw` | Prune a stalled, landing, landed, or retiring worker |
| `containers` | `cs` | Print the active containers |
| `volumes` | `vs` | List the active volumes |
| `curl` | `c` | curl the api |
| `get-wall` | `gw` | Get the current wall message |
| `set-wall` | `sw` | Set a wall message |
| `clear-wall` | `cw` | Clear the wall message |
| `completion` | -- | Generate shell completion code |

---

## Authentication

### Login

```bash
# Interactive login (opens browser for SSO)
fly -t TARGET login -c https://concourse.example.com -n TEAM

# Username/password login
fly -t TARGET login -c https://concourse.example.com -n TEAM -u USER -p PASS

# With CA certificate
fly -t TARGET login -c https://concourse.example.com --ca-cert ca.pem
```

**Flags:** `-c` concourse URL, `-n` team name, `-u` username, `-p` password, `--ca-cert`, `--client-cert`, `--client-key`

### Target Management

```bash
# List all saved targets with token expiry
fly targets

# Check auth status
fly -t TARGET status

# Download fly binary matching server version
fly -t TARGET sync

# Edit target URL or team
fly -t TARGET edit-target --concourse-url https://new-url.com --team-name new-team

# Delete a target
fly -t TARGET delete-target

# Delete all targets
fly delete-target -a

# Logout from a target
fly -t TARGET logout

# Logout from all targets
fly logout -a
```

**Token storage:** `~/.flyrc`. Tokens expire after one day. The `-t` flag is mandatory and stateless -- it prevents accidental cross-environment operations.

---

## Pipeline Operations

### Listing Pipelines

```bash
# List all pipelines
fly -t TARGET pipelines

# List only paused pipelines
fly -t TARGET paused-pipelines
```

### Setting Pipelines

```bash
# Set pipeline from YAML config
fly -t TARGET set-pipeline -p PIPELINE -c pipeline.yml

# With string variables
fly -t TARGET sp -p PIPELINE -c pipeline.yml -v branch=main -v env=staging

# With YAML variables
fly -t TARGET sp -p PIPELINE -c pipeline.yml -y config='{"key":"value"}'

# With instance variables
fly -t TARGET sp -p PIPELINE -c pipeline.yml -i branch=main

# Load variables from file
fly -t TARGET sp -p PIPELINE -c pipeline.yml -l vars.yml

# Non-interactive (skip confirmation prompt)
fly -t TARGET sp -p PIPELINE -c pipeline.yml -n

# Dry run (do not persist)
fly -t TARGET sp -p PIPELINE -c pipeline.yml -d

# Validate credentials against credential manager
fly -t TARGET sp -p PIPELINE -c pipeline.yml --check-creds
```

**Flags:** `-p` pipeline name, `-c` config file (or `-` for stdin), `-v` string var, `-y` YAML var, `-i` instance var, `-l` var file, `-n` non-interactive, `-d` dry run, `--check-creds`, `--no-color`, `--team`

### Validating and Formatting

```bash
# Validate pipeline config
fly validate-pipeline -c pipeline.yml

# Strict validation (fail on deprecation warnings)
fly vp -c pipeline.yml --strict

# Format pipeline config (print to stdout)
fly format-pipeline -c pipeline.yml

# Format in place
fly fp -c pipeline.yml --write
```

### Pipeline Lifecycle

```bash
# Get pipeline config as JSON
fly -t TARGET get-pipeline -p PIPELINE

# Pause pipeline (stops all resource checking and job scheduling)
fly -t TARGET pause-pipeline -p PIPELINE

# Unpause pipeline
fly -t TARGET unpause-pipeline -p PIPELINE

# Archive pipeline (permanently pauses, hides from default view)
fly -t TARGET archive-pipeline -p PIPELINE

# Expose pipeline (make publicly viewable without auth)
fly -t TARGET expose-pipeline -p PIPELINE

# Hide pipeline (reverse expose)
fly -t TARGET hide-pipeline -p PIPELINE

# Rename pipeline
fly -t TARGET rename-pipeline -o OLD_NAME -n NEW_NAME

# Destroy pipeline (PERMANENT - all data is deleted)
fly -t TARGET destroy-pipeline -p PIPELINE

# Order pipelines
fly -t TARGET order-pipelines -p PIPELINE_A -p PIPELINE_B -p PIPELINE_C
```

**WARNING:** `destroy-pipeline` permanently deletes the pipeline and ALL of its build history. This cannot be undone.

---

## Job Operations

```bash
# List jobs in a pipeline
fly -t TARGET jobs -p PIPELINE

# List paused jobs
fly -t TARGET paused-jobs -p PIPELINE

# Trigger a job
fly -t TARGET trigger-job -j PIPELINE/JOB

# Trigger and watch output
fly -t TARGET tj -j PIPELINE/JOB --watch

# Pause a job (prevent scheduling)
fly -t TARGET pause-job -j PIPELINE/JOB

# Unpause a job
fly -t TARGET unpause-job -j PIPELINE/JOB

# Request scheduler to run for a job
fly -t TARGET schedule-job -j PIPELINE/JOB
```

**Flags:** `-j` job in `PIPELINE/JOB` format, `--watch` for trigger-job

---

## Build Operations

### Listing Builds

```bash
# List 50 most recent builds (default)
fly -t TARGET builds

# List more builds
fly -t TARGET bs -c 100

# Filter by job
fly -t TARGET bs -j PIPELINE/JOB

# Filter by date range
fly -t TARGET bs --since '2025-01-01 00:00:00'
fly -t TARGET bs --until '2025-06-01 00:00:00'

# View builds from all teams
fly -t TARGET bs --all-teams

# JSON output
fly -t TARGET bs --json
```

**Flags:** `-c` count (default 50), `-j` pipeline/job filter, `--since`, `--until`, `--all-teams`, `--json`

### Watching Builds

```bash
# Watch most recent one-off build
fly -t TARGET watch

# Watch a specific build by global ID
fly -t TARGET w -b BUILD_ID

# Watch most recent build of a job
fly -t TARGET w -j PIPELINE/JOB

# Watch specific build of a job
fly -t TARGET w -j PIPELINE/JOB -b BUILD_NUMBER

# Ignore event parsing errors (version mismatch between fly and server)
fly -t TARGET w -b BUILD_ID --ignore-event-parsing-errors
```

**IMPORTANT:** Killing `fly watch` (Ctrl+C) does NOT abort the build. It only disconnects your terminal from the output stream. The build continues running on the server.

### Aborting Builds

```bash
# Abort by job + build number
fly -t TARGET abort-build -j PIPELINE/JOB -b BUILD_NUMBER

# Abort by global build ID (no -j flag)
fly -t TARGET ab -b GLOBAL_BUILD_ID

# Abort a build belonging to another team
fly -t TARGET ab -j PIPELINE/JOB -b BUILD_NUMBER --team OTHER_TEAM
```

**Flags:** `-j` pipeline/job, `-b` build number (with `-j`) or global build ID (without `-j`), `--team`

### Rerunning Builds

```bash
# Rerun build 4 of a job (uses same input versions)
fly -t TARGET rerun-build -j PIPELINE/JOB -b 4

# Rerun and watch
fly -t TARGET rb -j PIPELINE/JOB -b 4 --watch
```

Rerun builds use the same input versions as the original but run against the **current** job configuration. The rerun build name is appended with `.1` (e.g., `4.1`).

### One-Off Builds (execute)

```bash
# Execute a task from a config file
fly -t TARGET execute -c task.yml

# Provide inputs from local directories
fly -t TARGET e -c task.yml -i code=. -i stemcells=../stemcells

# Capture outputs to local directories
fly -t TARGET e -c task.yml -o artifact=/tmp/output

# Use inputs from a pipeline job
fly -t TARGET e -c task.yml --inputs-from PIPELINE/JOB

# Mix: pipeline inputs with local override
fly -t TARGET e -c task.yml --inputs-from PIPELINE/JOB -i my-repo=.

# Include .gitignored files
fly -t TARGET e -c task.yml --include-ignored

# Run privileged
fly -t TARGET e -c task.yml -p

# Target specific worker tag
fly -t TARGET e -c task.yml --tag my-worker-tag
```

**Flags:** `-c` task config, `-i` input mapping (name=path), `-o` output mapping, `--inputs-from` pipeline/job, `--include-ignored`, `-p` privileged, `--tag`, `--image`

---

## Resource Operations

```bash
# List resources in a pipeline
fly -t TARGET resources -p PIPELINE

# List resource versions
fly -t TARGET resource-versions -r PIPELINE/RESOURCE

# Check a resource (trigger version check)
fly -t TARGET check-resource -r PIPELINE/RESOURCE

# Check from a specific version
fly -t TARGET cr -r PIPELINE/RESOURCE --from ref:abc123

# Async check (return immediately, do not wait)
fly -t TARGET cr -r PIPELINE/RESOURCE --async

# Shallow check (resource itself only, not resource type)
fly -t TARGET cr -r PIPELINE/RESOURCE --shallow

# Check a resource type
fly -t TARGET check-resource-type -r PIPELINE/RESOURCE_TYPE

# Pin a resource to a version
fly -t TARGET pin-resource -r PIPELINE/RESOURCE -v ref:abc123

# Pin with a comment
fly -t TARGET pr -r PIPELINE/RESOURCE -v ref:abc123 -c "Pinned for hotfix"

# Add comment to already-pinned resource
fly -t TARGET pr -r PIPELINE/RESOURCE -c "Updated reason"

# Unpin a resource
fly -t TARGET unpin-resource -r PIPELINE/RESOURCE

# Enable/disable specific resource version
fly -t TARGET enable-resource-version -r PIPELINE/RESOURCE -v ref:abc123
fly -t TARGET disable-resource-version -r PIPELINE/RESOURCE -v ref:abc123

# Clear resource cache (all versions)
fly -t TARGET clear-resource-cache -r PIPELINE/RESOURCE

# Clear resource cache (specific version)
fly -t TARGET crc -r PIPELINE/RESOURCE -v digest:sha256@abc123

# Clear versions of a resource
fly -t TARGET clear-versions -r PIPELINE/RESOURCE

# Clear task cache for a step
fly -t TARGET clear-task-cache -j PIPELINE/JOB --step STEP_NAME

# Clear specific path within task cache
fly -t TARGET ctc -j PIPELINE/JOB --step STEP_NAME --cache-path path/in/cache
```

---

## Interactive Debugging (intercept / hijack)

The `intercept` command (alias `i`, also known as `hijack`) opens an interactive shell inside a build container.

```bash
# Intercept a step in the most recent build of a job
fly -t TARGET intercept -j PIPELINE/JOB -s STEP_NAME

# Intercept a specific build
fly -t TARGET i -j PIPELINE/JOB -b BUILD_NUMBER -s STEP_NAME

# Intercept a resource check container
fly -t TARGET i --check PIPELINE/RESOURCE

# Intercept by container handle (from fly containers output)
fly -t TARGET i --handle CONTAINER_HANDLE

# Run a specific command instead of a shell
fly -t TARGET i -j PIPELINE/JOB -s STEP_NAME ps auxf

# Windows workers
fly -t TARGET i -j PIPELINE/JOB -s STEP_NAME powershell
```

**Interceptable container states:** Only `created` and `failed` containers can be intercepted. Containers in other states are not available.

**Flags:** `-j` pipeline/job, `-b` build, `-s` step, `--check` pipeline/resource, `--handle` container handle

---

## Worker Management

### Worker States

Workers progress through a defined lifecycle. The state machine is implemented in `atc/db/worker_lifecycle.go`.

| State | Description | Accepts New Work | How Entered | How Exited |
|-------|-------------|------------------|-------------|------------|
| **running** | Healthy, heartbeating normally | Yes | Worker registers and heartbeats to TSA | Heartbeat expires -> stalled; `fly land-worker` -> landing; Worker process sends retire signal -> retiring |
| **stalled** | Stopped heartbeating, unreachable | No | Heartbeat expiry (`expires < NOW()`) | `fly prune-worker` removes it; Worker restarts and re-registers -> running |
| **landing** | Graceful drain in progress, finishing existing work | No (draining) | `fly land-worker` or SIGTERM to worker process | All non-interruptible builds complete -> landed |
| **landed** | Fully drained, no active work | No | All builds finish on a landing worker | Worker restarts -> running; `fly prune-worker` removes it |
| **retiring** | Permanently leaving the cluster | No (draining) | Worker process sends retire signal (e.g., scaling down) | All non-interruptible builds complete -> deleted from DB |

**Ephemeral workers** are automatically deleted from the database when their heartbeat expires, rather than transitioning to stalled.

**Non-interruptible builds** block the landing->landed and retiring->deleted transitions. A worker will remain in the landing or retiring state until these builds either complete or are aborted.

### Worker Commands

```bash
# List all registered workers
fly -t TARGET workers

# List with additional details (garden address, baggageclaim URL, active tasks, resource types)
fly -t TARGET ws --details

# JSON output
fly -t TARGET ws --json

# Land a worker (graceful drain)
fly -t TARGET land-worker -w WORKER_NAME

# Prune a specific non-running worker
fly -t TARGET prune-worker -w WORKER_NAME

# Prune all stalled workers
fly -t TARGET pw --all-stalled
```

**Output columns:** name, containers, platform, tags, team, state, version, age (plus garden address, baggageclaim url, active tasks, resource types with `--details`)

**Output grouping:** Workers are displayed in three groups: running (compatible), outdated (incompatible version, shown in red), stalled (with cleanup instructions).

**Pruning constraint:** Running workers cannot be pruned. They will re-register immediately. Only stalled, landing, landed, or retiring workers can be pruned.

### Container and Volume Inspection

```bash
# List active containers across all workers
fly -t TARGET containers

# JSON output
fly -t TARGET cs --json

# Container columns: handle, worker, pipeline, job, build #, build id, type, name, attempt

# List active volumes across all workers
fly -t TARGET volumes

# Detailed volume info (container handles, paths, resource types)
fly -t TARGET vs --details

# JSON output
fly -t TARGET vs --json

# Volume columns: handle, worker, type, identifier
# Sorted by worker name, then volume handle
```

---

## Troubleshooting Stuck Workers

### Diagnosis Flowchart

```
Is the worker listed in `fly workers` output?
|
+-- NO --> Worker process crashed or never registered
|          Action: Check worker host, restart worker process
|          If the host is gone: no action needed (ephemeral) or prune if it was static
|
+-- YES --> What state is the worker in?
    |
    +-- state = stalled
    |   |
    |   +-- Is the worker host reachable? (SSH, ping, etc.)
    |       |
    |       +-- YES --> Restart the worker process on the host
    |       |           (systemctl restart concourse-worker, or restart the container)
    |       |
    |       +-- NO  --> The host is gone. Prune the worker:
    |                   fly -t TARGET prune-worker -w WORKER_NAME
    |
    +-- state = running, but builds are not executing
    |   |
    |   +-- Check containerd health on the worker host
    |   +-- Check disk space (df -h) and memory (free -m)
    |   +-- Check for stale containerd socket (/run/containerd/containerd.sock)
    |   +-- Check worker logs for "connection refused" errors
    |
    +-- state = landing (stuck for a long time)
    |   |
    |   +-- Non-interruptible builds are blocking the transition
    |   +-- List builds on the worker: fly -t TARGET builds | grep WORKER_NAME
    |   +-- Abort stuck builds: fly -t TARGET abort-build -b BUILD_ID
    |   +-- Then prune: fly -t TARGET prune-worker -w WORKER_NAME
    |
    +-- state = retiring (stuck for a long time)
        |
        +-- Same as landing: abort remaining builds, then the worker
            will be automatically deleted from the database
```

### Common Causes

| Cause | Symptoms | Frequency |
|-------|----------|-----------|
| Dropped SSH tunnel to TSA | Worker goes stalled; TSA logs show "session closed" | Common in cloud/NAT environments |
| Stale containerd socket | Worker is running but containers fail to create; logs show "connection refused" to containerd socket | Common after unclean worker restarts |
| Network/firewall/NAT timeout | Worker heartbeat stops arriving at web node; worker goes stalled after timeout | Common with long-lived SSH tunnels through NAT |
| Disk full on worker | Container creation fails; GC cannot reclaim volumes; builds fail with I/O errors | Common on high-throughput workers |
| OOM (out of memory) | Worker process or containerd killed by kernel OOM killer; worker goes stalled | Common with many concurrent containers |
| SSH key mismatch | Worker cannot register; TSA rejects connection; "ssh: handshake failed" in logs | After key rotation or worker reprovisioning |
| Container.Run hanging | Build step appears to complete but web node never receives exit event; build stuck in running state | Seen pre-v7.9; related to containerd/Garden communication |
| API request stampeding | Web node overwhelmed by concurrent resource checks or scheduler requests; workers appear slow | Large installations with many pipelines sharing resources |
| Stuck GC (garbage collection) | Volumes and containers accumulate; disk fills up; "volume cannot be destroyed as children are present" | After failed builds with volume dependencies |

### Step-by-Step Fix Procedures

#### 1. Identify the Problem Worker

```bash
# List all workers, check for non-running states
fly -t TARGET workers

# JSON output for scripting
fly -t TARGET ws --json

# Check containers on the worker
fly -t TARGET containers | grep WORKER_NAME

# Check volumes on the worker
fly -t TARGET volumes | grep WORKER_NAME
```

#### 2. Reachable Stalled Worker -- Restart

```bash
# SSH to the worker host and restart the worker process
ssh worker-host "systemctl restart concourse-worker"

# Or if running in Docker/K8s, restart the container
kubectl delete pod concourse-worker-xyz  # K8s will recreate it
docker restart concourse-worker          # Docker
```

After restart, the worker will re-register with the web node and appear as `running`.

#### 3. Unreachable Stalled Worker -- Prune

```bash
# Remove the stalled worker from the cluster
fly -t TARGET prune-worker -w WORKER_NAME

# Or prune all stalled workers at once
fly -t TARGET pw --all-stalled
```

Builds that were assigned to the pruned worker will be marked as errored. The scheduler will re-queue jobs automatically.

#### 4. Stuck Landing Worker -- Abort Blocking Builds

```bash
# Find builds still running on the landing worker
fly -t TARGET builds --json | jq '.[] | select(.worker_name == "WORKER_NAME" and .status == "started")'

# Abort each stuck build
fly -t TARGET abort-build -b BUILD_ID

# After all builds are aborted, the worker transitions to landed
# Then prune it if needed
fly -t TARGET prune-worker -w WORKER_NAME
```

#### 5. Builds Stuck on Dead Worker

When a worker dies with builds still attributed to it, those builds hang indefinitely in the `started` state because the web node keeps waiting for events.

```bash
# Find builds on the dead worker
fly -t TARGET builds --json | jq '.[] | select(.worker_name == "DEAD_WORKER" and .status == "started") | .id'

# Prune the worker (builds will be errored automatically)
fly -t TARGET prune-worker -w DEAD_WORKER

# Or abort specific builds first
fly -t TARGET abort-build -b BUILD_ID
```

#### 6. Stale containerd Socket Fix

When containerd exits uncleanly (e.g., `kill -9`), the socket file at `/run/containerd/containerd.sock` persists. On restart, Garden may fail to connect because containerd has not yet re-initialized the socket.

```bash
# On the worker host, remove the stale socket
ssh worker-host "rm -f /run/containerd/containerd.sock"

# Restart the worker process
ssh worker-host "systemctl restart concourse-worker"
```

**Prevention:** Mount a tmpfs at `/run/containerd` so stale sockets are automatically removed on container/host restart. See concourse/concourse#6752 for details.

#### 7. Stuck Garbage Collection Fix

When volumes cannot be destroyed due to child dependencies, GC stalls and disk usage grows.

```bash
# Check volumes on the problem worker
fly -t TARGET volumes --details | grep WORKER_NAME

# Check containers -- orphaned containers can hold volume references
fly -t TARGET containers | grep WORKER_NAME

# If the worker is accessible, restart it to reset GC state
ssh worker-host "systemctl restart concourse-worker"

# If volumes are truly stuck, a full worker drain may be required
fly -t TARGET land-worker -w WORKER_NAME
# Wait for drain, then restart the worker
```

### Decision Matrix: Prune vs Land vs Restart vs Retire

| Situation | Action | Command | Effect |
|-----------|--------|---------|--------|
| Worker stalled, host is gone | **Prune** | `fly pw -w NAME` | Removes from DB; builds errored |
| Worker stalled, host is reachable | **Restart** | Restart process on host | Worker re-registers as running |
| Planned maintenance, keep host | **Land** | `fly lw -w NAME` | Drains work, transitions to landed |
| Scaling down, removing host permanently | **Retire** | Send retire signal to worker process | Drains work, then deletes from DB |
| Worker landing too long | **Abort + Prune** | `fly ab` then `fly pw` | Forcefully clears the worker |
| All stalled workers after an outage | **Prune all** | `fly pw --all-stalled` | Bulk cleanup |

### Common Error Messages

| Error Message | Cause | Solution |
|---------------|-------|----------|
| `write: broken pipe` | SSH tunnel to TSA dropped; the web node lost its connection to the worker | Check network stability; increase SSH keepalive settings; restart worker to re-establish tunnel |
| `connection refused` (to containerd socket) | Containerd process is not running or socket is stale from unclean shutdown | Remove stale socket at `/run/containerd/containerd.sock`; restart containerd and the worker process |
| `cannot_invalidate_during_initialization` | A resource cache is being cleared while it is still being initialized | Wait for the resource check to complete before clearing the cache; retry the operation |
| `volume cannot be destroyed as children are present` | GC cannot reclaim a volume because dependent child volumes still exist | Restart the worker to reset GC state; if persistent, land the worker and restart |
| `failed to register` / `heartbeat failed` | Worker cannot reach the TSA (web node) to register or send heartbeats | Verify network connectivity from worker to web node; check TSA port accessibility; verify SSH keys |
| `context deadline exceeded` | An operation timed out, typically a network call from worker to web or vice versa | Check network latency; increase relevant timeout settings; check for resource exhaustion |
| `ssh: handshake failed` | SSH key mismatch between worker and TSA; keys were rotated or worker was reprovisioned with wrong keys | Regenerate worker keys and distribute the public key to the web/TSA node; restart both |
| `too many open files` | Worker or web node hit the file descriptor limit due to too many containers, volumes, or connections | Increase `ulimit -n` on the affected host; consider reducing concurrent work or adding workers |

### Health Monitoring

Use these commands to proactively detect worker issues:

```bash
# Find non-running workers
fly -t TARGET ws --json | jq '[.[] | select(.state != "running")] | length'

# List non-running workers with details
fly -t TARGET ws --json | jq '.[] | select(.state != "running") | {name, state, platform, containers}'

# Find workers with zero containers (may indicate they are not receiving work)
fly -t TARGET ws --json | jq '.[] | select(.containers == 0 and .state == "running") | .name'

# Count containers per worker (detect imbalance)
fly -t TARGET ws --json | jq '.[] | select(.state == "running") | {name, containers}' | jq -s 'sort_by(.containers) | reverse'

# Check API health via curl
fly -t TARGET curl /api/v1/info -- --silent | jq .

# Check goroutine count (high counts may indicate goroutine leaks)
fly -t TARGET curl /api/v1/info -- --silent | jq .worker_count
```

---

## Tuning Reference

Environment variables for Concourse web node performance tuning. Source: `docs/docs/operation/tuning.md`.

### Build Log Retention

| Variable | Purpose | Default |
|----------|---------|---------|
| `CONCOURSE_DEFAULT_BUILD_LOGS_TO_RETAIN` | Builds to keep per job (user-overridable) | unlimited |
| `CONCOURSE_MAX_BUILD_LOGS_TO_RETAIN` | Max builds per job (user-overridable) | unlimited |
| `CONCOURSE_DEFAULT_DAYS_TO_RETAIN_BUILD_LOGS` | Age threshold before deletion (user-overridable) | unlimited |
| `CONCOURSE_MAX_DAYS_TO_RETAIN_BUILD_LOGS` | Hard age limit (cannot be overridden) | unlimited |

### Resource Checking

| Variable | Purpose | Default |
|----------|---------|---------|
| `CONCOURSE_RESOURCE_CHECKING_INTERVAL` | Interval between resource version checks | ~1 minute |
| `CONCOURSE_RESOURCE_WITH_WEBHOOK_CHECKING_INTERVAL` | Interval for webhook-enabled resources | ~1 minute |
| `CONCOURSE_MAX_CHECKS_PER_SECOND` | Rate limiter for concurrent checks (`-1` to disable) | -- |

### Garbage Collection

| Variable | Purpose | Default |
|----------|---------|---------|
| `CONCOURSE_GC_FAILED_GRACE_PERIOD` | How long to keep failed job containers | 120 hours |
| `CONCOURSE_GC_ONE_OFF_GRACE_PERIOD` | How long to keep one-off build containers | 5 minutes |
| `CONCOURSE_GC_MISSING_GRACE_PERIOD` | How long to keep containers for missing resources | 5 minutes |
| `CONCOURSE_GC_HIJACK_GRACE_PERIOD` | How long to keep intercepted (hijacked) containers | 5 minutes |

### Pipeline and Task Limits

| Variable | Purpose |
|----------|---------|
| `CONCOURSE_PAUSE_PIPELINES_AFTER` | Auto-pause inactive pipelines (e.g., 90 days) |
| `CONCOURSE_DEFAULT_TASK_CPU_LIMIT` | Default CPU limit for tasks |
| `CONCOURSE_DEFAULT_TASK_MEMORY_LIMIT` | Default memory limit for tasks |
| `CONCOURSE_DEFAULT_GET_TIMEOUT` | Default timeout for get steps |
| `CONCOURSE_DEFAULT_PUT_TIMEOUT` | Default timeout for put steps |
| `CONCOURSE_DEFAULT_TASK_TIMEOUT` | Default timeout for task steps |

### Infrastructure Ratio

Recommended web-to-worker ratio: **1:6** (baseline). The Concourse core team operates at **1:8** with a smaller user base. Start at 1:6 and adjust based on API latency and scheduler throughput.

### Container Placement Strategies

Set via `CONCOURSE_CONTAINER_PLACEMENT_STRATEGY`:

| Strategy | Behavior |
|----------|----------|
| `volume-locality` (default) | Places containers on workers where most inputs already exist; reduces streaming but may cause hotspots |
| `fewest-build-containers` | Places on worker with fewest active build containers; ignores long-lived check containers |
| `random` | No optimization; random placement |
| `limit-active-tasks` (experimental) | Tracks active task count per worker; supports max task limit |
| `limit-active-containers` | Filters out workers above a container threshold; best combined with other strategies |
| `limit-active-volumes` | Filters out workers above a volume threshold; best combined with other strategies |

Strategies can be chained. Each strategy filters the worker pool before passing to the next. If the final strategy returns multiple eligible workers, selection is random.

---

## Executable Skills

TypeScript skill wrappers available in the `fly/` and `concourse/` directories.

### fly/ Skills (CLI wrapper)

| Skill | File | Description |
|-------|------|-------------|
| `login` | `fly/login.ts` | Authenticate with a Concourse target |
| `list_pipelines` | `fly/list_pipelines.ts` | List all pipelines |
| `get_pipeline` | `fly/get_pipeline.ts` | Get pipeline configuration as JSON |
| `set_pipeline` | `fly/set_pipeline.ts` | Create or update a pipeline from YAML |
| `validate_pipeline` | `fly/validate_pipeline.ts` | Validate a pipeline YAML file |
| `trigger_job` | `fly/trigger_job.ts` | Trigger a job in a pipeline |
| `list_builds` | `fly/list_builds.ts` | List recent builds with optional filters |
| `watch_build` | `fly/watch_build.ts` | Watch or retrieve build output |
| `workers` | `fly/workers.ts` | List registered workers with state and metadata |
| `prune_worker` | `fly/prune_worker.ts` | Prune a stalled, landing, landed, or retiring worker |
| `land_worker` | `fly/land_worker.ts` | Land a worker (graceful drain) |
| `containers` | `fly/containers.ts` | List active containers across workers |
| `abort_build` | `fly/abort_build.ts` | Abort a running build |

### concourse/ Skills (REST API)

| Skill | File | Description |
|-------|------|-------------|
| `list_pipelines` | `concourse/list_pipelines.ts` | List all pipelines for the team |
| `get_pipeline` | `concourse/get_pipeline.ts` | Get pipeline details |
| `get_pipeline_config` | `concourse/get_pipeline_config.ts` | Get pipeline configuration (YAML) |
| `set_pipeline` | `concourse/set_pipeline.ts` | Set or update pipeline configuration |
| `pause_pipeline` | `concourse/pause_pipeline.ts` | Pause a pipeline |
| `unpause_pipeline` | `concourse/unpause_pipeline.ts` | Unpause a pipeline |
| `list_jobs` | `concourse/list_jobs.ts` | List all jobs for a pipeline |
| `trigger_job` | `concourse/trigger_job.ts` | Trigger a new build for a job |
| `get_build` | `concourse/get_build.ts` | Get build details by ID |
| `list_builds` | `concourse/list_builds.ts` | List builds for a job |
| `list_resources` | `concourse/list_resources.ts` | List resources for a pipeline |

**Note:** `retire-worker` is intentionally excluded from the executable skills. Retiring a worker permanently removes it from the cluster after draining, which is too destructive for automation. Use `fly land-worker` (graceful drain with re-registration possible) or `fly prune-worker` (remove non-running worker) instead. Reserve `retire-worker` for manual infrastructure scaling operations.

---

## Documentation Sources

### Official Concourse Documentation (concourse/docs)

| Path | Content |
|------|---------|
| `docs/docs/fly.md` | Fly CLI command reference: login, targets, status, sync, logout, userinfo, edit-target, delete-target, completion |
| `docs/docs/pipelines.md` | Pipeline configuration schema and set-pipeline step |
| `docs/docs/jobs.md` | Job configuration, trigger-job, pause-job, unpause-job, clear-task-cache |
| `docs/docs/builds.md` | Build commands: builds, watch, execute, intercept, abort-build, rerun-build |
| `docs/docs/tasks.md` | Task configuration, fly execute flags: -c, -i, -o, --inputs-from, --include-ignored |
| `docs/docs/operation/administration.md` | Worker management: fly workers, prune-worker, land-worker, containers, volumes, curl |
| `docs/docs/operation/tuning.md` | Performance tuning env vars: log retention, resource checking, GC, timeouts, web:worker ratio |
| `docs/docs/operation/container-placement.md` | Container placement strategies: volume-locality, fewest-build-containers, random, limit-active-tasks |

### Concourse Source Code (concourse/concourse)

| Path | Content |
|------|---------|
| `fly/commands/fly.go` | Master command registration: all 64 commands with aliases and descriptions |
| `fly/commands/workers.go` | Workers command: `--details`, `--json` flags; output columns and grouping |
| `fly/commands/prune_worker.go` | Prune worker: `-w` worker, `--all-stalled`; running workers cannot be pruned |
| `fly/commands/land_worker.go` | Land worker: `-w` worker flag |
| `fly/commands/abort_build.go` | Abort build: `-j` job, `-b` build, `--team` flags |
| `fly/commands/containers.go` | Containers command: `--json`, `--team` flags; 9 output columns |
| `fly/commands/volumes.go` | Volumes command: `--details`, `--json` flags; sorted by worker then handle |
| `fly/commands/set_pipeline.go` | Set pipeline: `-p`, `-c`, `-v`, `-y`, `-i`, `-l`, `-n`, `-d`, `--check-creds` flags |
| `fly/commands/check_resource.go` | Check resource: `-r`, `--from`, `--async`, `--shallow` flags |
| `fly/commands/pin_resource.go` | Pin resource: `-r`, `-v`, `-c` flags; version matching pins latest |
| `fly/commands/unpin_resource.go` | Unpin resource: `-r` flag |
| `fly/commands/clear_resource_cache.go` | Clear resource cache: `-r`, `-v` flags; requires confirmation |
| `fly/commands/resources.go` | Resources: `-p`, `--json`, `--team`; columns: name, type, pinned, check status |
| `atc/db/worker_lifecycle.go` | Worker state machine: running, stalled, landing, landed, retiring transitions and SQL |

### Relevant GitHub Issues

| Issue | Title | Relevance |
|-------|-------|-----------|
| concourse/concourse#6752 | If containerd socket is interrupted, worker is stuck in limbo | Stale socket fix, tmpfs workaround, beacon signal handling |
| concourse/concourse#7318 | Task finished but build never ended | Container.Run hang scenario, web node event stream failure |
| concourse/concourse#750 | Workers stop heartbeating | Historical SSH tunnel stability issues |
| concourse/concourse#8172 | "no running task found" after upgrade to 7.7.0 | Containerd task lookup failure post-upgrade |

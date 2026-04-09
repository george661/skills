---
name: loop-pipeline
description: Concourse CI build monitoring helpers for loop commands. Check build status across repos and determine readiness to proceed.
---

# Loop Pipeline Monitoring

## Purpose

Provides helpers for monitoring Concourse CI builds during loop execution, enabling intelligent pause/resume decisions.

---

## Check All Repos for Active Builds

Determine if any the project repository has active Concourse builds:

```bash
#!/bin/bash
# Check all repos for active Concourse builds

repos=("frontend-app" "api-service" "auth-service")
any_active=false
active_count=0

for repo in "${repos[@]}"; do
  echo "Checking $repo..."

  # List recent builds for repo pipeline
  builds=$(npx tsx .claude/skills/fly/list_builds.ts '{
    "pipeline": "'"$repo"'",
    "count": 25
  }')

  # Filter for active builds (started or pending)
  active=$(echo "$builds" | jq '[.builds[] | select(.status == "started" or .status == "pending")]')

  active_in_repo=$(echo "$active" | jq 'length')

  if [ "$active_in_repo" -gt 0 ]; then
    any_active=true
    active_count=$((active_count + active_in_repo))
    echo "  $repo: $active_in_repo active build(s)"
    echo "$active" | jq -r '.[] | "    - build #\(.id) job=\(.job_name) pipeline=\(.pipeline_name) (\(.status))"'
  else
    echo "  $repo: no active builds"
  fi
done

echo ""
if [ "$any_active" = true ]; then
  echo "Total active builds: $active_count"
else
  echo "No active builds across all repos"
fi
```

---

## Check Most Recent Build for Pipeline

Monitor the most recent build status for a Concourse pipeline:

```bash
#!/bin/bash
# Check most recent build status for a pipeline
# Usage: check_pipeline_build <repo>

repo="$1"

# List recent builds for the pipeline
builds=$(npx tsx .claude/skills/fly/list_builds.ts '{
  "pipeline": "'"$repo"'",
  "count": 25
}')

# Get the most recent build
latest=$(echo "$builds" | jq '.builds[0] // null')

if [ "$latest" = "null" ] || [ -z "$latest" ]; then
  echo "No builds found for pipeline: $repo"
  exit 1
fi

# Extract details
build_id=$(echo "$latest" | jq -r '.id')
status=$(echo "$latest" | jq -r '.status')
job_name=$(echo "$latest" | jq -r '.job_name')
pipeline_name=$(echo "$latest" | jq -r '.pipeline_name')
start_time=$(echo "$latest" | jq -r '.start_time // 0')

# Determine status flags
is_complete="false"
is_successful="false"
is_failed="false"

if [ "$status" != "started" ] && [ "$status" != "pending" ]; then
  is_complete="true"
fi

if [ "$status" = "succeeded" ]; then
  is_successful="true"
fi

if [ "$status" = "failed" ]; then
  is_failed="true"
fi

# Output result as JSON
cat <<EOF
{
  "found": true,
  "pipeline": "$pipeline_name",
  "jobName": "$job_name",
  "buildId": $build_id,
  "status": "$status",
  "startTime": $start_time,
  "isComplete": $is_complete,
  "isSuccessful": $is_successful,
  "isFailed": $is_failed
}
EOF
```

---

## Wait for Build with Timeout

Poll a Concourse build until completion or timeout:

```bash
#!/bin/bash
# Wait for Concourse build to complete with timeout
# Usage: wait_for_build <build-id> [max-wait-seconds] [poll-interval-seconds]

build_id="$1"
max_wait_seconds="${2:-300}"      # 5 minutes default
poll_interval_seconds="${3:-15}"  # 15 seconds default

poll_start_time=$(date +%s)
last_status=""

while true; do
  current_time=$(date +%s)
  elapsed=$((current_time - poll_start_time))

  if [ "$elapsed" -ge "$max_wait_seconds" ]; then
    echo "TIMEOUT after $elapsed seconds"
    cat <<EOF
{
  "completed": false,
  "status": "TIMEOUT",
  "elapsed": $elapsed
}
EOF
    exit 1
  fi

  # Get build details
  build=$(npx tsx .claude/skills/concourse/get_build.ts '{
    "build_id": '"$build_id"'
  }')

  status=$(echo "$build" | jq -r '.status')
  build_start=$(echo "$build" | jq -r '.start_time // 0')
  build_end=$(echo "$build" | jq -r '.end_time // 0')

  # Compute duration from start_time and end_time
  if [ "$build_end" -gt 0 ] && [ "$build_start" -gt 0 ]; then
    duration=$((build_end - build_start))
  else
    duration=0
  fi

  # Show progress if status changed
  if [ "$status" != "$last_status" ]; then
    echo "Build status: $status (elapsed: ${elapsed}s)"
    last_status="$status"
  fi

  # Check if complete (not started or pending)
  if [ "$status" != "started" ] && [ "$status" != "pending" ]; then
    success="false"
    if [ "$status" = "succeeded" ]; then
      success="true"
    fi

    cat <<EOF
{
  "completed": true,
  "status": "$status",
  "duration": $duration,
  "success": $success
}
EOF
    exit 0
  fi

  # Wait before next poll
  sleep "$poll_interval_seconds"
done
```

---

## Get Failed Job Logs

Retrieve logs from failed Concourse jobs:

```bash
#!/bin/bash
# Get logs from failed Concourse jobs
# Usage: get_failed_job_logs <repo>

repo="$1"

# List all jobs for the pipeline
jobs=$(npx tsx .claude/skills/concourse/list_jobs.ts '{
  "pipeline_name": "'"$repo"'"
}')

# Filter for jobs whose finished_build has status "failed"
failed_jobs=$(echo "$jobs" | jq '[.[] | select(.finished_build.status == "failed")]')
failed_count=$(echo "$failed_jobs" | jq 'length')

if [ "$failed_count" -eq 0 ]; then
  echo "No failed jobs found"
  exit 0
fi

echo "Found $failed_count failed job(s)"
echo ""

# Get logs for each failed job's finished build
echo "$failed_jobs" | jq -c '.[]' | while read -r job; do
  job_name=$(echo "$job" | jq -r '.name')
  build_id=$(echo "$job" | jq -r '.finished_build.id')

  echo "=== $job_name (build #$build_id) ==="

  # Get build log via fly watch
  log=$(npx tsx .claude/skills/fly/watch_build.ts '{
    "build_id": '"$build_id"'
  }' 2>&1)

  if [ $? -eq 0 ]; then
    # Extract output and show last 5000 characters
    echo "$log" | jq -r '.output // empty' | tail -c 5000
  else
    echo "ERROR: Could not retrieve log: $log"
  fi

  echo ""
  echo ""
done
```

---

## Check Deploy Build Status

Check if a deploy build is running or recently completed in Concourse:

```bash
#!/bin/bash
# Check deploy build status in Concourse
# Usage: check_deploy_build <repo>

repo="$1"

# List recent builds for the pipeline
builds=$(npx tsx .claude/skills/fly/list_builds.ts '{
  "pipeline": "'"$repo"'",
  "count": 25
}')

# Find the most recent build (Concourse pipelines map to repos)
deploy_build=$(echo "$builds" | jq '.builds[0] // null')

if [ "$deploy_build" = "null" ] || [ -z "$deploy_build" ]; then
  echo '{"found": false}'
  exit 0
fi

# Extract details
build_id=$(echo "$deploy_build" | jq -r '.id')
pipeline_name=$(echo "$deploy_build" | jq -r '.pipeline_name')
job_name=$(echo "$deploy_build" | jq -r '.job_name')
status=$(echo "$deploy_build" | jq -r '.status')
start_time=$(echo "$deploy_build" | jq -r '.start_time // 0')

# Calculate age in minutes from start_time (epoch seconds)
current_timestamp=$(date +%s)
if [ "$start_time" -gt 0 ]; then
  age_minutes=$(( (current_timestamp - start_time) / 60 ))
else
  age_minutes=0
fi

# Determine status flags
is_recent="false"
if [ "$age_minutes" -lt 30 ]; then
  is_recent="true"
fi

is_active="false"
if [ "$status" = "started" ] || [ "$status" = "pending" ]; then
  is_active="true"
fi

# Output result as JSON
cat <<EOF
{
  "found": true,
  "buildId": $build_id,
  "pipeline": "$pipeline_name",
  "jobName": "$job_name",
  "status": "$status",
  "startTime": $start_time,
  "ageMinutes": $age_minutes,
  "isRecent": $is_recent,
  "isActive": $is_active
}
EOF
```

---

## Build Decision Matrix

Use this to decide whether to wait or pause:

| Build Status | Duration | Decision |
|-------------|----------|----------|
| pending | < 2 min | Wait inline |
| started | < 5 min | Wait inline |
| started | > 5 min | Pause and move on |
| failed | Any | Trigger /fix-pipeline or /fix-pr |
| succeeded | Any | Continue to next phase |

```bash
#!/bin/bash
# Decide what action to take based on Concourse build status
# Usage: decide_build_action <repo>

repo="$1"

# Check pipeline build status (using function from previous section)
status=$(bash check_pipeline_build.sh "$repo" 2>&1)

if [ $? -ne 0 ]; then
  # No build found
  cat <<EOF
{
  "action": "no-build",
  "canProceed": true
}
EOF
  exit 0
fi

# Extract status fields
is_successful=$(echo "$status" | jq -r '.isSuccessful')
is_failed=$(echo "$status" | jq -r '.isFailed')
build_id=$(echo "$status" | jq -r '.buildId')
start_time=$(echo "$status" | jq -r '.startTime')

# Check if successful
if [ "$is_successful" = "true" ]; then
  cat <<EOF
{
  "action": "proceed",
  "canProceed": true
}
EOF
  exit 0
fi

# Check if failed
if [ "$is_failed" = "true" ]; then
  cat <<EOF
{
  "action": "fix-required",
  "canProceed": false,
  "buildId": $build_id,
  "nextCommand": "/fix-pr"
}
EOF
  exit 0
fi

# Still running - check duration
current_timestamp=$(date +%s)
if [ "$start_time" -gt 0 ]; then
  duration_minutes=$(( (current_timestamp - start_time) / 60 ))
else
  duration_minutes=0
fi

if [ "$duration_minutes" -lt 5 ]; then
  estimated_wait=$((5 - duration_minutes))
  cat <<EOF
{
  "action": "wait-inline",
  "canProceed": false,
  "estimatedWaitMinutes": $estimated_wait,
  "buildId": $build_id
}
EOF
  exit 0
fi

# Running too long - pause
cat <<EOF
{
  "action": "pause-and-continue",
  "canProceed": false,
  "reason": "Build running too long",
  "buildId": $build_id
}
EOF
```

---

## Usage in Loop Commands

**Before starting new work:**
```bash
# Check if any builds are currently active
active_count=$(bash check_all_builds_active.sh | grep "Total active builds" | awk '{print $4}')

if [ "$active_count" -gt 0 ]; then
  echo "$active_count builds running - checking waiting issues first"
fi
```

**After PR creation:**
```bash
# Decide what to do based on build status
decision=$(bash decide_build_action.sh "frontend-app")
action=$(echo "$decision" | jq -r '.action')

if [ "$action" = "wait-inline" ]; then
  build_id=$(echo "$decision" | jq -r '.buildId')
  bash wait_for_build.sh "$build_id" 300 15
elif [ "$action" = "pause-and-continue" ]; then
  # Store pause state and move on
  npx tsx .claude/skills/agentdb/store.ts '{
    "namespace": "${TENANT_NAMESPACE}",
    "key": "loop-state-PROJ-123",
    "value": {"status": "paused", "reason": "PR build still running"}
  }'
  exit 0
fi
```

**On build failure:**
```bash
# Get decision for build
decision=$(bash decide_build_action.sh "frontend-app")
action=$(echo "$decision" | jq -r '.action')

if [ "$action" = "fix-required" ]; then
  # Get failed job logs
  bash get_failed_job_logs.sh "frontend-app"

  # Trigger fix-pr command
  echo "Build failed - run: /fix-pr PROJ-123"
fi
```

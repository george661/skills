---
name: loop-state
description: Manage loop state for pause/resume functionality. Handles labels, comments, and memory for loop commands.
---

# Loop State Management

## Purpose

Provides helper functions for managing loop state across issues, enabling pause/resume functionality when waiting for pipelines.

## State Labels

| Label | Meaning |
|-------|---------|
| `loop-waiting-pipeline` | Issue paused waiting for CI/CD pipeline |
| `loop-waiting-deploy` | Issue paused waiting for deployment |
| `loop-in-progress` | Issue actively being processed by loop |
| `loop-blocked` | Issue blocked and skipped by loop |

---

## Pause Issue for Pipeline

When a loop command needs to pause for a pipeline:

```bash
pause_for_pipeline() {
  local issue_key="$1"
  local pause_reason="$2"
  local phase="$3"
  local pr_number="$4"
  local branch="$5"
  local repo="$6"
  local pipeline_uuid="$7"

  # 1. Get current labels and add waiting label
  current_labels=$(npx tsx .claude/skills/jira-mcp/get_issue.ts "{\"issue_key\": \"$issue_key\", \"fields\": \"labels\"}" | jq -r '.fields.labels | join(",")')
  new_labels=$(echo "$current_labels" | tr ',' '\n' | grep -v "^loop-" | tr '\n' ',' | sed 's/,$//')
  new_labels="${new_labels},loop-waiting-pipeline"

  npx tsx .claude/skills/jira-mcp/update_issue.ts "{\"issue_key\": \"$issue_key\", \"labels\": [\"$new_labels\"], \"notify_users\": false}"

  # 2. Comment with pause state
  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  comment_body="**Loop Paused - Waiting for Pipeline**

**Reason:** $pause_reason
**Paused At:** $timestamp

**State Snapshot:**
- Phase: $phase
- PR: ${pr_number:-N/A}
- Branch: ${branch:-N/A}
- Repo: $repo
- Pipeline: ${pipeline_uuid:-checking...}

**Resume:** Run \`/loop:issue $issue_key --resume\` or wait for next backlog loop."

  npx tsx .claude/skills/jira-mcp/add_comment.ts "{\"issue_key\": \"$issue_key\", \"body\": \"$comment_body\"}"

  # 3. Store state in memory
  npx tsx .claude/skills/agentdb/reflexion_store_episode.ts({
    action: "store",
    namespace: "${TENANT_NAMESPACE}",
    key: "loop-state-$issue_key",
    value: "{\"phase\": \"$phase\", \"prNumber\": \"$pr_number\", \"branch\": \"$branch\", \"repo\": \"$repo\", \"pipelineUuid\": \"$pipeline_uuid\", \"pausedAt\": \"$timestamp\", \"pauseReason\": \"$pause_reason\", \"status\": \"waiting-pipeline\"}",
    ttl: 604800
  })

  echo "{\"status\": \"paused\", \"reason\": \"$pause_reason\"}"
}
```

---

## Resume from Pause

When resuming a paused issue:

```bash
resume_from_pause() {
  local issue_key="$1"

  # 1. Load state from memory
  state_json=$(npx tsx .claude/skills/agentdb/reflexion_store_episode.ts({
    action: "retrieve",
    namespace: "${TENANT_NAMESPACE}",
    key: "loop-state-$issue_key"
  }))

  if [[ -z "$state_json" || "$state_json" == "null" ]]; then
    # No saved state - start fresh
    echo "{\"canResume\": false, \"reason\": \"no-saved-state\"}"
    return
  fi

  # Parse state
  phase=$(echo "$state_json" | jq -r '.phase')
  repo=$(echo "$state_json" | jq -r '.repo')
  pipeline_uuid=$(echo "$state_json" | jq -r '.pipelineUuid')
  next_action=$(echo "$state_json" | jq -r '.nextAction // "next phase"')

  # 2. Check if pipeline is complete
  if [[ -n "$pipeline_uuid" && -n "$repo" ]]; then
    pipeline=$(npx tsx .claude/skills/concourse/get_build.ts "{\"build_id\": $pipeline_uuid}")
    pipeline_state=$(echo "$pipeline" | jq -r '.status')

    if [[ "$pipeline_state" == "started" || "$pipeline_state" == "pending" ]]; then
      echo "{\"canResume\": false, \"reason\": \"pipeline-still-running\", \"pipeline\": $pipeline}"
      return
    fi

    if [[ "$pipeline_state" == "failed" ]]; then
      echo "{\"canResume\": true, \"state\": $state_json, \"nextAction\": \"fix-pipeline\", \"pipeline\": $pipeline}"
      return
    fi
  fi

  # 3. Clear waiting label
  current_labels=$(npx tsx .claude/skills/jira-mcp/get_issue.ts "{\"issue_key\": \"$issue_key\", \"fields\": \"labels\"}" | jq -r '.fields.labels | join(",")')
  new_labels=$(echo "$current_labels" | tr ',' '\n' | grep -v "^loop-" | tr '\n' ',' | sed 's/,$//')
  new_labels="${new_labels},loop-in-progress"

  npx tsx .claude/skills/jira-mcp/update_issue.ts "{\"issue_key\": \"$issue_key\", \"labels\": [\"$new_labels\"], \"notify_users\": false}"

  # 4. Comment on resume
  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  comment_body="**Loop Resumed**

**Resumed At:** $timestamp
**Previous Phase:** $phase
**Continuing with:** $next_action"

  npx tsx .claude/skills/jira-mcp/add_comment.ts "{\"issue_key\": \"$issue_key\", \"body\": \"$comment_body\"}"

  echo "{\"canResume\": true, \"state\": $state_json, \"nextAction\": \"$next_action\"}"
}
```

---

## Check Loop State

Query the current state of a loop:

```bash
check_loop_state() {
  local issue_key="$1"

  # Check memory first
  memory_state=$(npx tsx .claude/skills/agentdb/reflexion_store_episode.ts({
    action: "retrieve",
    namespace: "${TENANT_NAMESPACE}",
    key: "loop-state-$issue_key"
  }))

  # Check Jira labels
  issue_data=$(npx tsx .claude/skills/jira-mcp/get_issue.ts "{\"issue_key\": \"$issue_key\", \"fields\": \"labels,status\"}")

  labels=$(echo "$issue_data" | jq -r '.fields.labels[]' | grep "^loop-" | jq -R . | jq -s .)
  jira_status=$(echo "$issue_data" | jq -r '.fields.status.name')

  is_waiting=$(echo "$labels" | jq 'any(. == "loop-waiting-pipeline")')
  is_blocked=$(echo "$labels" | jq 'any(. == "loop-blocked")')
  is_in_progress=$(echo "$labels" | jq 'any(. == "loop-in-progress")')

  if [[ -n "$memory_state" && "$memory_state" != "null" ]]; then
    saved_state="$memory_state"
  else
    saved_state="null"
  fi

  cat <<EOF
{
  "issueKey": "$issue_key",
  "jiraStatus": "$jira_status",
  "loopLabels": $labels,
  "isWaiting": $is_waiting,
  "isBlocked": $is_blocked,
  "isInProgress": $is_in_progress,
  "savedState": $saved_state
}
EOF
}
```

---

## Clear Loop State

Clean up loop state when issue completes:

```bash
clear_loop_state() {
  local issue_key="$1"
  local outcome="$2"

  # 1. Remove all loop labels
  current_labels=$(npx tsx .claude/skills/jira-mcp/get_issue.ts "{\"issue_key\": \"$issue_key\", \"fields\": \"labels\"}" | jq -r '.fields.labels | join(",")')
  clean_labels=$(echo "$current_labels" | tr ',' '\n' | grep -v "^loop-" | jq -R . | jq -s .)

  npx tsx .claude/skills/jira-mcp/update_issue.ts "{\"issue_key\": \"$issue_key\", \"labels\": $clean_labels, \"notify_users\": false}"

  # 2. Delete memory state
  npx tsx .claude/skills/agentdb/reflexion_store_episode.ts({
    action: "delete",
    namespace: "${TENANT_NAMESPACE}",
    key: "loop-state-$issue_key"
  })

  # 3. Comment completion
  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  comment_body="**Loop Complete**

**Outcome:** $outcome
**Completed At:** $timestamp

Issue has been processed through the full loop lifecycle."

  npx tsx .claude/skills/jira-mcp/add_comment.ts "{\"issue_key\": \"$issue_key\", \"body\": \"$comment_body\"}"
}
```

---

## Helper: Get Issue Labels

```bash
get_issue_labels() {
  local issue_key="$1"

  npx tsx .claude/skills/jira-mcp/get_issue.ts "{\"issue_key\": \"$issue_key\", \"fields\": \"labels\"}" | jq -r '.fields.labels[]'
}
```

---

## State Machine

```
           ┌─────────────┐
           │   START     │
           └──────┬──────┘
                  │
                  ▼
    ┌─────────────────────────┐
    │   loop-in-progress      │
    │   (actively working)    │
    └────────┬────────────────┘
             │
    ┌────────┴────────┐
    │                 │
    ▼                 ▼
┌────────────┐  ┌────────────────┐
│  COMPLETE  │  │ loop-waiting-  │
│   (done)   │  │    pipeline    │
└────────────┘  └───────┬────────┘
                        │
               Pipeline │ completes
                        │
                        ▼
              ┌─────────────────┐
              │ Resume or       │
              │ fix-pipeline    │
              └─────────────────┘
```

---

## Usage Examples

**Pause during PR pipeline:**
```bash
pause_for_pipeline "PROJ-123" "PR pipeline running" "pr-created" "456" "PROJ-123/fix-button" "frontend-app" "abc-123"
```

**Resume on next loop:**
```bash
result=$(resume_from_pause "PROJ-123")
can_resume=$(echo "$result" | jq -r '.canResume')

if [[ "$can_resume" == "true" ]]; then
  # Continue from saved state
  phase=$(echo "$result" | jq -r '.state.phase')
  continue_from_phase "$phase" "$result"
else
  # Still waiting
  reason=$(echo "$result" | jq -r '.reason')
  echo "Still waiting: $reason"
fi
```

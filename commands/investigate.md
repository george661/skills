<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Investigate CloudWatch alarms from AWS - analyze metrics, logs, and root cause
arguments:
  - name: alarm
    description: CloudWatch alarm name or ARN (e.g., "api-service-error-rate-high" or full ARN)
    required: true
  - name: region
    description: AWS region (defaults to us-east-1)
    required: false
  - name: timerange
    description: Time range to analyze (e.g., "1h", "6h", "24h") - defaults to 1h
    required: false
---

# Investigate CloudWatch Alarm: $ARGUMENTS.alarm

## Overview

This command investigates CloudWatch alarms by:
1. Retrieving alarm details and current state
2. Querying related CloudWatch metrics
3. Searching CloudWatch Logs for correlated errors
4. Analyzing patterns to determine root cause
5. Creating a Jira issue if a bug is identified
6. Storing findings in memory for future reference

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

1. Phase 0: Load context and verify AWS access
2. Phase 1: Get alarm details and state history
3. Phase 2: Query related CloudWatch metrics
4. Phase 3: Search CloudWatch Logs for errors
5. Phase 4: Analyze patterns and determine root cause
6. Phase 5: Create Jira issue if bug identified
7. Phase 6: Store findings and generate report

**START NOW: Begin Phase 0/Step 0.**

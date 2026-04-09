<!-- MODEL_TIER: sonnet -->
<!-- DISPATCH: Spawn a Task subagent with model: "sonnet" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Sonnet. -->

---
description: Fix a failed Concourse CI build and trigger validation on success
arguments:
  - name: issue
    description: Jira issue key (e.g., PROJ-123) with a failed pipeline
    required: true
  - name: pipeline_url
    description: URL to the specific failed pipeline (optional, will be auto-detected)
    required: false
  - name: branch
    description: Branch where the pipeline failed (main, develop, or deploy/*)
    required: false
---

# Fix Failed Pipeline: $ARGUMENTS.issue

## Purpose

This command is triggered by the issue-daemon when a Concourse CI build fails. It can handle failures on:
- **Main/develop branches**: Initial build/deploy failures
- **Deploy/* branches**: Post-deployment test failures

**Typical Flow:**
1. Pipeline fails (any branch)
2. Daemon triggers `/fix-pipeline $ARGUMENTS.issue`
3. Agent creates a bug issue to track the fix work (via `/bug`)
4. Agent investigates failure, implements fix
5. Agent pushes fix to main
6. Pipeline re-runs -> If succeeded on deploy/* branch, daemon triggers validation
7. Agent closes the bug issue after validation passes

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

1. Phase 0: Load context, identify repository, and parse TESTING.md
2. Phase 0.5: Create bug issue to track fix work
3. Phase 1: Get failed pipeline details and logs
4. Phase 2: Analyze failure and determine fix strategy
5. Phase 3: Implement fix and validate via TESTING.md
6. Phase 4: Rebase to main, push fix, and monitor pipeline
7. Phase 5: Update Jira with results

**START NOW: Begin Phase 0/Step 0.**

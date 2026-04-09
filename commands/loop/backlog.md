<!-- MODEL_TIER: opus -->
<!-- DISPATCH: Spawn a Task subagent with model: "opus" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Opus. -->

---
description: Process the entire Jira backlog in priority order until completion
arguments:
  - name: max_iterations
    description: Maximum number of issues to process (optional, default unlimited)
    required: false
  - name: project
    description: Jira project key (default PROJ)
    required: false
---

# Loop Backlog

## Purpose

This command processes the entire Jira backlog in strict priority order:

1. **Validation issues** - Closest to Done, validate first
2. **Failed PRs/Pipelines** - Fix these before starting new work
3. **Bug type issues** - Fix bugs before features
4. **Other To Do issues** - Tasks, stories, etc.

The loop intelligently:
- Pauses issues waiting for pipelines
- Skips blocked issues
- Resumes waiting issues when pipelines complete
- Continues until backlog is clear or max iterations reached

---

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

1. Phase 0: Initialize loop and check pipeline status
2. Phase 1: Build priority queue from backlog
3. Phase 2: Check for resumable waiting issues
4. Phase 3: Process next priority issue
5. Phase 4: Evaluate and continue or complete

**START NOW: Begin Phase 0/Step 0.**

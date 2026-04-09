<!-- MODEL_TIER: sonnet -->
<!-- DISPATCH: Spawn a Task subagent with model: "sonnet" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Sonnet. -->

---
description: Generate release notes from git history and Jira issues across project repositories
arguments:
  - name: since
    description: Start date in YYYY-MM-DD format (defaults to last Friday)
    required: false
  - name: until
    description: End date in YYYY-MM-DD format (defaults to today)
    required: false
  - name: repos
    description: Comma-separated list of repos (defaults to auth-service,lambda-functions,frontend-app)
    required: false
---

# Release Notes Generator

## Overview

This command generates comprehensive release notes by:

1. Collecting git commits from specified repositories since the given date
2. Fetching completed Jira issues (status = Done) in the time period
3. Categorizing changes by type (features, bug fixes, improvements)
4. Generating a formatted markdown document
5. Saving to project-docs/operations/releases/
6. Committing and pushing to remote

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

1. Phase 1: Calculate date range and parse arguments
2. Phase 2: Fetch git history from all repositories
3. Phase 3: Fetch completed Jira issues
4. Phase 4: Categorize and correlate changes
5. Phase 5: Generate release notes document
6. Phase 6: Save to project-docs and summarize
7. Phase 7: Commit and push to remote

**START NOW: Begin Phase 0/Step 0.**

<!-- MODEL_TIER: opus -->
<!-- DISPATCH: Spawn a Task subagent with model: "opus" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Opus. -->

---
description: Work all issues in a Jira Epic through to completion
arguments:
  - name: epic
    description: Jira Epic key (e.g., PROJ-711)
    required: true
  - name: skip_planning
    description: Skip planning phase (use only when resuming)
    required: false
---

# Loop Epic: $ARGUMENTS.epic

## Purpose

This command processes all child issues in an Epic through to completion using a **strategic planning-first approach**. It:

1. **Plans first** - Analyzes all issues, groups by repository, identifies gaps
2. **Confidence checks** - Verifies readiness before starting work
3. **Works in parallel** - Groups issues by repository, doesn't block on CI
4. **Validates completion** - Ensures all issues are Done AND deployed

**Usage:** `/loop:epic PROJ-711`

---

## Definition of Done (CRITICAL)

An Epic is ONLY complete when ALL of the following are true:

- [ ] All child issues have status = Done
- [ ] No gaps in design or implementation (all functionality covered)
- [ ] All changes deployed to development environment
- [ ] All functionality verified working in dev

---

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

1. Phase 0: Strategic planning and gap analysis
2. Phase 1: Review plan twice (ultrathink)
3. Phase 2: Process issues by repository batch
4. Phase 3: Handle async CI/review results
5. Phase 4: Validate completion and deployment

**START NOW: Begin Phase 0/Step 0.**

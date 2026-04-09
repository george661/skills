<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Output sequence analysis as JSON for machine processing (no Jira comments added)
---

# Sequence Analysis - JSON Output Mode

## Purpose

This command performs the same analysis as `/sequence` but outputs results as structured JSON for machine processing, CI/CD integration, or downstream automation. **No Jira comments are added in this mode.**

## Key Differences from `/sequence`

| Aspect | `/sequence` | `/sequence:json` |
|--------|-------------|------------------|
| Output format | Human-readable summary + Jira comments | Structured JSON |
| Jira updates | Adds/updates comments on each issue | None - read-only |
| Use case | Developer coordination | Automation, dashboards, CI/CD |
| Memory storage | Stores sequence-latest | Stores with `-json` suffix |

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

1. Phase 0: Initialize session and load memory context
2. Phase 1: Fetch all active issues from Jira
3. Phase 2: Download issues to local filesystem
4. Phase 3: Fetch pipeline data and calculate build times
5. Phase 4: Analyze dependencies between issues
6. Phase 5: Determine optimal sequencing
7. Phase 6: Generate JSON output
8. Phase 7: Store results and output

**START NOW: Begin Phase 0/Step 0.**

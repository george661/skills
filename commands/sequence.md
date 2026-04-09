<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Analyze active Jira issues, determine optimal sequencing based on dependencies and build times, and update issues with coordination instructions
---

# Sequence Active Issues

## Phase 0: Link & Label Integrity Check (MANDATORY)

**HARD GATE -- run before any sequencing logic.**

### Step 1: Verify Parent Epics

For every issue in scope:
- Verify the parent epic exists and is not Done. If orphaned (no parent): flag and ask user.
- Clean stale step/outcome labels from completed workflows (e.g., `step:implementing` on a
  Done issue, `outcome:failure-*` on a now-passing issue).

### Step 2: Verify Epic Issue Links

For every epic in scope:
- Verify issue links exist (blocks/is_blocked_by between epics with dependencies).
- If the epic description mentions dependencies but no links exist: flag the gap and ask
  user to confirm link creation.
  ```bash
  npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "{epic_key}", "fields": ["description", "issuelinks"]}'
  ```
- Verify the epic has child issues. If empty: flag as potentially stale.

### Step 3: Cross-Epic Dependency Verification

Walk the blocks/is_blocked_by graph across all epics:
- **Circular dependencies**: If A blocks B blocks C blocks A, flag the cycle and ask user
  which link to remove.
- **Orphan epics**: Epics with no dependency links at all. Flag for review (may be intentional
  standalone work).
- **Done blockers**: If issue X `is_blocked_by` issue Y, and Y is Done, clean the blocking
  link (the dependency is satisfied).

### Step 4: Skeleton-First Ordering

Within each epic:
- Skeleton issues (label = `skeleton`) are sequenced first.
- Non-skeleton issues are sequenced after all skeleton issues for their epic are validated.
- If skeleton issues exist but none have `outcome:success-validation`: all non-skeleton
  issues in that epic are marked as blocked.

---

## Phase 0.5: Retrieve Relevant Patterns

**Retrieve patterns before sequencing issues:**

```bash
# Search for issue sequencing patterns
npx tsx ~/.claude/skills/agentdb/pattern_search.ts '{"task": "issue sequencing patterns", "k": 5, "threshold": 0.6}'

# Retrieve relevant episodes for sequence dependencies
npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts '{"task": "sequence dependencies", "k": 3}'
```

**Pattern Review:**
- [ ] Reviewed patterns for dependency analysis
- [ ] Noted successful sequencing strategies
- [ ] Applied lessons from prior coordination

---

## Purpose

This command examines all active work (To Do, In Progress, Validation) across the platform project, analyzes dependencies, considers Concourse CI build times for each workflow stage, and updates each issue with specific coordination instructions.

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

0. Phase 0: Link & Label Integrity Check
1. Phase 0.5: Initialize session and load memory context
2. Phase 1: Fetch all active issues from Jira (To Do, In Progress, Validation)
3. Phase 2: Download issues to local filesystem for analysis
4. Phase 3: Fetch build data and calculate build times per repo
5. Phase 4: Analyze dependencies between issues
6. Phase 5: Determine optimal sequencing
7. Phase 6: Update each issue with dependency comments
8. Phase 7: Store sequence in memory and cleanup

**START NOW: Begin Phase 0/Step 0.**

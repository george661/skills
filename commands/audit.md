<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Audit a deployed URL by testing role-based access, capturing evidence, comparing to specs, and auto-creating bugs
arguments:
  - name: url
    description: Full URL to audit (e.g., "https://d3p2yqofgy75sz.cloudfront.net/admin/content")
    required: true
---

# Audit URL: $ARGUMENTS.url

## Overview

This command performs **role-based UI compliance testing** by:
1. Collecting specifications from PRPs and Jira for the target URL
2. Determining applicable roles via smart URL path detection
3. Automating browser sessions for each role using Playwright utilities
4. Capturing evidence (screenshots, console logs, network requests)
5. Analyzing discrepancies between actual behavior and specifications
6. Auto-creating bugs via hybrid /bug integration for any issues found

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

1. Phase 0: Load memory, search for specs in PRPs and Jira
2. Phase 1: Determine applicable roles from URL path
3. Phase 2: Execute browser automation for each role
4. Phase 3: Analyze evidence against specifications
5. Phase 4: Create bugs for discrepancies found
6. Phase 5: Cleanup temp files, store results in memory

**START NOW: Begin Phase 0/Step 0.**
---

## Pattern Learning Integration

**Audit outcomes are stored in AgentDB for future pattern retrieval.**

At phase completion, record the pattern:
```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{"session_id": "${TENANT_NAMESPACE}", "task": "audit-phase-N", "reward": 0.9, "success": true}'
```

Phase-specific patterns captured:
- `audit-phase-0`: Spec collection quality
- `audit-phase-1`: Role detection accuracy
- `audit-phase-2`: Browser automation reliability
- `audit-phase-3`: Analysis accuracy
- `audit-phase-4`: Bug creation workflow
- `audit-phase-5`: Cleanup and reporting

**Final completion pattern:**
```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{"session_id": "${TENANT_NAMESPACE}", "task": "workflow-audit-complete", "reward": 0.9, "success": true, "metadata": {"audit": "audit-${AUDIT_TIMESTAMP}"}}'
```

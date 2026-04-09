<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Refresh local Jira issue cache for garden commands.
---

# Garden: Cache Refresh

Fetches all Backlog/Grooming issues from Jira and caches them locally.

## Execution

Run the cache script:

```bash
$PROJECT_ROOT/agents/scripts/garden/garden-cache.sh
```

Force refresh even if cache is fresh:

```bash
$PROJECT_ROOT/agents/scripts/garden/garden-cache.sh --force
```

## Cache Location

```
~/.cache/garden/
├── issues/
│   ├── index.json      # Issue list with metadata
│   └── PROJ-*.json       # Individual issues
├── active/
│   └── index.json      # To Do, In Progress, Validation issues
├── prps/               # (NEW) PRP index from ${PROJECT_ROOT}/${DOCS_REPO}/prps/
│   ├── index.json
│   └── {prp-slug}.json
├── design-sessions/    # (NEW) Design session states from ${DESIGN_DOCS_PATH}/sessions/
│   ├── index.json
│   └── {session-id}.json
└── cache-meta.json     # Timestamp and stats (extended — see below)
```

## Cache TTL

- **Fresh**: <1 hour - use without warning
- **Stale**: 1-4 hours - use with warning
- **Expired**: >4 hours - should refresh

## Cache Sections

`cache-meta.json` stores per-section timestamps alongside the existing flat fields:

```json
{
  "createdAt": "...",
  "expiresAt": "...",
  "config": { ... },
  "stats": { ... },
  "sections": {
    "issues": { "fetchedAt": "...", "count": N },
    "prps": { "fetchedAt": "...", "count": N },
    "designSessions": { "fetchedAt": "...", "count": N }
  }
}
```

The flat `createdAt`/`expiresAt` fields are preserved — existing subcommands (`garden-relevancy`, `garden-accuracy`, `garden-readiness`) read these for TTL checking and are unaffected.

`garden-consistency` and `garden-consolidate` read the new `prps/` and `design-sessions/` sections. When these sections are absent, those subcommands log a skip message and exit cleanly.

## After Caching

Run analysis commands:
- `/garden` - Full analysis (6 phases) with auto-apply
- `/garden-relevancy` - Duplicate and target check
- `/garden-accuracy` - Solution drift check
- `/garden-readiness` - Dependency analysis and sequencing
- `/garden-consistency` - Cross-PRP and design session conflict detection (requires prps/ + design-sessions/ cache sections)
- `/garden-consolidate` - Issue batching candidate identification

## Garden Workflow

```
/garden-cache           # Step 1: Refresh cache
     |
     v
/garden                 # Step 2: Analyze + auto-apply (6 phases)
     |
     +-- Phase 1-3: Relevancy, accuracy, readiness (existing)
     +-- Phase 4: Consistency check (requires prps/ + design-sessions/ cache)
     +-- Phase 5: Consolidation candidates
     +-- Phase 6: Writes sequence manifest to AgentDB
     +-- Closes irrelevant issues, adds fresh-YYYYMMDD labels, adds comments
     |
     v
sequence.json           # Output file
```

## Clear Cache

```bash
rm -rf ~/.cache/garden
```

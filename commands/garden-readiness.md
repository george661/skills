<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Analyze backlog/grooming issues for dependencies and determine sequencing position.
---

# Garden: Readiness Analysis

Identifies dependencies and determines if issues are ready to move to "To Do".

## Prerequisites

Cache must exist at `~/.cache/garden/`. If missing, run `/garden-cache` first.

## Execution

### 1. Setup

```bash
mkdir -p /tmp/garden-analysis/readiness
```

### 2. Load issues from cache

```typescript
const CACHE_DIR = `${process.env.HOME}/.cache/garden`;
const index = JSON.parse(Read(`${CACHE_DIR}/issues/index.json`));
const active = JSON.parse(Read(`${CACHE_DIR}/active/index.json`));
```

### 3. Analyze dependencies for each issue

**Explicit links (from issuelinks field):**
- `blocks` / `is blocked by`
- `depends on` / `is dependency of`

**Implicit (from description):**
- "after PROJ-XXX", "requires PROJ-XXX", "blocked by PROJ-XXX"
- "once PROJ-XXX is done", "prerequisite: PROJ-XXX"

**Cross-repo (inferred):**
- frontend-app depends on api-service depends on auth-service
- Same epic + different repos = likely dependency

### 4. Calculate sequence position

- `early` - No blockers, multiple dependents (do first)
- `middle` - Some blockers and some dependents
- `late` - Multiple blockers (do later)
- `anytime` - No dependencies either direction

### 5. Assess readiness

Ready for "To Do" when:
- All explicit blockers resolved
- Relevancy check passed (if run)
- Accuracy check passed (if run)
- Description has sufficient detail (>100 chars)

### 6. Save results

Per issue, save to `/tmp/garden-analysis/readiness/{KEY}.json`:
```json
{
  "key": "PROJ-123",
  "ready": true,
  "confidence": 0.85,
  "mustCompleteBefore": [
    {"issue": "PROJ-100", "reason": "Jira link: blocked by", "type": "explicit"}
  ],
  "shouldCompleteAfter": [
    {"issue": "PROJ-200", "reason": "This unblocks PROJ-200", "type": "explicit"}
  ],
  "blockers": [],
  "sequencePosition": "early",
  "recommendation": "ready"
}
```

Recommendations: `ready` | `blocked` | `needs-grooming`

### 7. Auto-apply results (optional)

Run the apply script to add fresh labels and comments:
```bash
$PROJECT_ROOT/agents/scripts/garden/garden-apply.sh
```

Or dry-run first:
```bash
$PROJECT_ROOT/agents/scripts/garden/garden-apply.sh --dry-run
```

The script will:
- **Add `fresh-YYYYMMDD` label** to issues where `ready == true` (e.g., `fresh-20260108`)
- **Add comments** with marker `Garden Analysis: Readiness`:

```
Garden Analysis: Readiness

READY (85% confidence)
- Sequence position: early
- Label added: fresh-20260108
- Unblocks: PROJ-200, PROJ-201
```

Or for blocked issues:
```
Garden Analysis: Readiness

BLOCKED (70% confidence)
- Sequence position: late
- Must wait for: PROJ-100, PROJ-101
- Blocked by: PROJ-100 (explicit Jira link)
```

### 8. Report

```
## Readiness Analysis Complete

| Status | Count |
|--------|-------|
| Ready | X |
| Blocked | Y |
| Needs Grooming | Z |

### Sequence Position
| Position | Issues |
|----------|--------|
| Early | PROJ-1, PROJ-2 |
| Middle | PROJ-3 |
| Late | PROJ-4, PROJ-5 |
| Anytime | PROJ-6 |

### Auto-Actions Available
Run garden-apply.sh to:
- Add fresh-20260108 label to: PROJ-1, PROJ-2, PROJ-3, PROJ-6
- Add readiness comments to all analyzed issues

### Do First (unblocks most): PROJ-1 (5 dependents)
### Waiting On: PROJ-4 -> PROJ-100, PROJ-101
```

### 9. Output: sequence.json

The apply script generates `/tmp/garden-analysis/output/sequence.json`:
```json
{
  "sequence": [
    {"key": "PROJ-1", "ready": true, "sequencePosition": "early", "blockedBy": [], "unblocks": ["PROJ-4", "PROJ-5"]},
    {"key": "PROJ-2", "ready": true, "sequencePosition": "early", "blockedBy": [], "unblocks": []},
    {"key": "PROJ-3", "ready": true, "sequencePosition": "middle", "blockedBy": [], "unblocks": ["PROJ-4"]},
    {"key": "PROJ-4", "ready": false, "sequencePosition": "late", "blockedBy": ["PROJ-1", "PROJ-3"], "unblocks": []}
  ]
}
```

<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Scan PRPs and design sessions for cross-document conflicts and inconsistencies.
---

# Garden: Consistency Analysis

Detects conflicting approaches, assumption drift, and scope overlap across open PRPs and design sessions. Never auto-resolves — surfaces all findings for human review.

## Prerequisites

Cache must exist at `~/.cache/garden/` with `prps/` and `design-sessions/` sections populated. If missing or stale, run `/garden-cache` first.

## Execution

### 1. Setup

```bash
mkdir -p /tmp/garden-analysis/consistency
```

### 2. Load PRP and design-session indexes from cache

```typescript
const CACHE_DIR = `${process.env.HOME}/.cache/garden`;
const prpIndex = JSON.parse(Read(`${CACHE_DIR}/prps/index.json`));
const sessionIndex = JSON.parse(Read(`${CACHE_DIR}/design-sessions/index.json`));
```

If either index is missing, output "No PRP/session data in cache — run /garden-cache first" and exit gracefully.

### 3. Build scope map

For each PRP and design session, extract:
- **Affected repositories** (from frontmatter `domain` field or description keywords: `api-service`, `frontend-app`, `auth-service`, `lambda-functions`, etc.)
- **Domain areas** (from `domain` frontmatter: `sessions`, `tokens`, `marketplace`, `auth`, `organizations`, `publishers`, `platform`, `infrastructure`)
- **Affected modules/paths** (specific files or packages mentioned in title or description)

### 4. Identify overlapping pairs

Compare all pairs (PRP vs PRP, PRP vs session, session vs session):
- **Same repository + same domain** = candidate for conflict check
- **Same module or path mentioned** = candidate for scope overlap

Skip pairs where both items are Done, archived, or have `status: archived` frontmatter.

### 5. Classify conflicts per overlapping pair

For each overlapping pair, determine severity:

- **`approach-conflict`** (blocking): Two documents propose different solutions for the same module or problem.
- **`assumption-drift`** (warning): A PRP's stated assumptions no longer match its linked design session.
- **`scope-overlap`** (informational): Two epics claim the same files or APIs without explicit coordination note.

### 6. Save results

For each conflict found, save to `/tmp/garden-analysis/consistency/{KEY_A}-{KEY_B}.json`:
```json
{
  "docA": "PROJ-123",
  "docB": "PROJ-456",
  "severity": "approach-conflict",
  "description": "Both documents propose conflicting approaches for the same module",
  "affectedRepo": "api-service",
  "affectedPath": "pkg/auth/",
  "recommendation": "Resolve before implementing either epic"
}
```

Save summary to `/tmp/garden-analysis/output/consistency-report.json`:
```json
{
  "metadata": {
    "generatedAt": "2026-01-01T00:00:00Z",
    "prpsScanned": 0,
    "sessionsScanned": 0
  },
  "conflicts": [],
  "summary": {
    "approachConflicts": 0,
    "assumptionDrift": 0,
    "scopeOverlap": 0
  }
}
```

### 7. Write Jira comments for approach-conflicts only

For each `approach-conflict`, add a `[consistency-check]` comment to BOTH issue keys:

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts "{\"issue_key\": \"PROJ-XXX\", \"body\": \"[consistency-check]\\nseverity: approach-conflict\\nconflicts-with: PROJ-YYY\\ndescription: {description}\\nrecommendation: {recommendation}\\ngenerated: $(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
```

For `assumption-drift` and `scope-overlap`: write to the report file only.

### 8. Report

```
## Consistency Analysis Complete

| Severity | Count |
|----------|-------|
| approach-conflict (blocking) | N |
| assumption-drift (warning) | N |
| scope-overlap (informational) | N |

### Approach Conflicts (Require Human Resolution)
- **PROJ-123 vs PROJ-456**: {description}
  → {recommendation}

### Output Files
- consistency-report.json: /tmp/garden-analysis/output/consistency-report.json
```

If no conflicts found: output "Consistency check passed — no conflicts detected across N PRPs and M design sessions."

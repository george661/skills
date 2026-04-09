<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Check backlog/grooming issues for duplicates and verify target code still exists.
---

# Garden: Relevancy Analysis

Checks if issues are still relevant by detecting duplicates and validating target code exists.

## Prerequisites

Cache must exist at `~/.cache/garden/`. If missing, run `/garden-cache` first.

## Execution

### 1. Setup

```bash
mkdir -p /tmp/garden-analysis/relevancy
```

### 2. Load issues from cache

```typescript
const CACHE_DIR = `${process.env.HOME}/.cache/garden`;
const index = JSON.parse(Read(`${CACHE_DIR}/issues/index.json`));
const issueKeys = index.issues.map(i => i.key);
```

### 3. Analyze each issue

For each issue, determine:

**Duplicate Detection:**
```bash
# Search Jira for similar issues
npx tsx ~/.claude/skills/issues/search_issues.ts '{"jql": "project = ${PROJECT_KEY} AND summary ~ \"keyword\" AND key != PROJ-123", "fields": ["key", "summary", "status"], "max_results": 10}'
# Calculate similarity: summary overlap (0.4) + description (0.3) + component (0.2) + label (0.1)
# Flag as duplicate if similarity > 0.8
```

**Target Validation:**
```typescript
// Extract file paths from description
// Use Glob to find: Glob(`**/${filename}`)
// Use Grep to find: Grep({ pattern: componentName, path: repoPath })
// Target exists if any match found
```

### 4. Save results

Per issue, save to `/tmp/garden-analysis/relevancy/{KEY}.json`:
```json
{
  "key": "PROJ-123",
  "relevant": true,
  "confidence": 0.85,
  "duplicates": [{"key": "PROJ-456", "similarity": 0.7}],
  "targetExists": true,
  "targetLocation": "src/components/Example.tsx",
  "recommendation": "keep"
}
```

Recommendations: `keep` | `close` | `merge` | `update`

### 5. Auto-apply results (optional)

Run the apply script to automatically close irrelevant issues and add comments:
```bash
$PROJECT_ROOT/agents/scripts/garden/garden-apply.sh
```

Or dry-run first:
```bash
$PROJECT_ROOT/agents/scripts/garden/garden-apply.sh --dry-run
```

The script will:
- **Close issues** where `relevant == false` or `recommendation == "close"`
- **Add comments** with marker `Garden Analysis: Relevancy`:

```
Garden Analysis: Relevancy

RELEVANT (85% confidence)
- Target exists: true
- Target location: src/components/Example.tsx
- No duplicates found
```

### 6. Report

```
## Relevancy Analysis Complete

| Status | Count |
|--------|-------|
| Relevant | X |
| Duplicates Found | Y |
| Target Missing | Z |

### Auto-Actions Available
Run garden-apply.sh to:
- Close: PROJ-1, PROJ-2 (irrelevant)
- Merge: PROJ-3 -> PROJ-4 (duplicate)
```

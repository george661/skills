<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Identify issues that can be batched together for a single PR to improve delivery velocity.
---

# Garden: Consolidation Analysis

Finds issues that overlap in scope and could be worked together in one PR. Never modifies issues automatically — outputs candidates for human review.

## Prerequisites

Cache must exist at `~/.cache/garden/`. If missing or stale, run `/garden-cache` first.

## Execution

### 1. Setup

```bash
mkdir -p /tmp/garden-analysis/consolidation
```

### 2. Load issues from cache

```typescript
const CACHE_DIR = `${process.env.HOME}/.cache/garden`;
const index = JSON.parse(Read(`${CACHE_DIR}/issues/index.json`));
```

Load all Backlog, Grooming, and To Do issues. Skip In Progress or beyond.

### 3. Check for prior declinations

```bash
npx tsx ~/.claude/skills/agentdb/recall_query.ts '{"query": "consolidation-decline", "k": 20}'
```

Build a set of declined pairs from results. Key format: `consolidation-decline:{keyA}:{keyB}`.

### 4. Identify consolidation candidates

Check each pair of issues for these criteria:

**Criterion A — Same repository + overlapping file paths**: Two issues that mention the same files or directories in description or acceptance criteria.

**Criterion B — Sequential issues in same epic targeting same module**: Issues with the same `parent` epic that both mention the same package, service, or directory.

**Criterion C — Low-complexity batching**: Issues labeled `size:xs` or `story-points: 1` where 3+ such issues exist in the same epic.

Skip pairs where:
- Either issue already has a `consolidate-with:*` label
- Either issue is In Progress, Validation, or Done
- The pair appears in the prior declinations set

### 5. Save candidates

For each candidate pair (confidence ≥ 0.70), save to `/tmp/garden-analysis/consolidation/{KEY_A}-{KEY_B}.json`:
```json
{
  "keyA": "PROJ-123",
  "keyB": "PROJ-456",
  "criterion": "same-repo-overlapping-paths",
  "rationale": "Both touch functions/users/ — could be one PR",
  "suggestedLabel": "consolidate-with:PROJ-456",
  "confidence": 0.85
}
```

Save summary to `/tmp/garden-analysis/output/consolidate-candidates.json`:
```json
{
  "metadata": {
    "generatedAt": "2026-01-01T00:00:00Z",
    "issuesScanned": 0,
    "pairsChecked": 0
  },
  "candidates": [],
  "summary": {
    "overlappingPaths": 0,
    "sequentialSameModule": 0,
    "lowComplexityBatch": 0
  }
}
```

### 6. Write Jira consolidation hints (confidence ≥ 0.80 only)

For each qualifying candidate, add a `[consolidation-hint]` comment to BOTH issues:

```bash
npx tsx ~/.claude/skills/issues/add_comment.ts "{\"issue_key\": \"PROJ-XXX\", \"body\": \"[consolidation-hint]\\nconsolidate-with: PROJ-YYY\\ncriterion: same-repo-overlapping-paths\\nrationale: Both touch functions/users/ — could be one PR\\nconfidence: 0.85\\naction: Add label consolidate-with:PROJ-YYY to both issues after human review\\ngenerated: $(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
```

Do NOT add labels or modify issues in any other way — comments only.

### 7. Report

```
## Consolidation Analysis Complete

| Criterion | Pairs Found |
|-----------|-------------|
| Same repo, overlapping paths | N |
| Sequential same-module issues | N |
| Low-complexity batch candidates | N |

### Consolidation Candidates
- **PROJ-123 + PROJ-456**: Both touch functions/users/ — could be one PR (confidence: 85%)
  → Run: garden-apply.sh --consolidation to add consolidate-with labels after review

### Output Files
- consolidate-candidates.json: /tmp/garden-analysis/output/consolidate-candidates.json
```

If no candidates found: output "Consolidation check complete — no batching opportunities found across N issues."

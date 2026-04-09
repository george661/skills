<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Review backlog/grooming issues for relevancy, accuracy, and readiness. Uses cached issues from ~/.cache/garden/
---

# Garden Command

Analyzes issues in Backlog/Grooming for: duplicates, solution drift, and sequencing. **Automatically applies results** by closing done issues, adding fresh labels, and adding garden comments.

## Prerequisites

Run cache refresh first (if cache is >4 hours old):
```bash
$PROJECT_ROOT/agents/scripts/garden/garden-cache.sh
```

## Automatic Actions

After analysis completes, this command automatically:
1. **Closes "already done" issues** - Transitions irrelevant issues to Done with explanation
2. **Adds fresh-YYYYMMDD labels** - Tags ready issues with today's date (e.g., `fresh-20260108`)
3. **Adds garden comments** - Adds structured comments to all analyzed issues

## Phase 0: Retrieve Relevant Patterns

**Retrieve patterns before gardening backlog:**

```bash
# Search for backlog analysis patterns
npx tsx ~/.claude/skills/agentdb/pattern_search.ts '{"task": "garden backlog analysis patterns", "k": 5, "threshold": 0.6}'

# Retrieve relevant episodes for gardening
npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts '{"task": "garden backlog relevancy", "k": 3}'
```

**Pattern Review:**
- [ ] Reviewed patterns for backlog analysis
- [ ] Noted common stale issue indicators
- [ ] Applied successful gardening approaches

---

## Execution

### 1. Check cache

Check cache:
```typescript
const CACHE_DIR = `${process.env.HOME}/.cache/garden`;
const meta = Read(`${CACHE_DIR}/cache-meta.json`);
const index = Read(`${CACHE_DIR}/issues/index.json`);
// If cache missing or expired (>4h), tell user to run: /garden-cache
```

### 2. Setup and spawn parallel analyzers

```bash
mkdir -p /tmp/garden-analysis/{relevancy,accuracy,readiness,output}
cp ~/.cache/garden/issues/*.json /tmp/garden-analysis/
```

**SPAWN ALL THREE IN SINGLE MESSAGE:**

```typescript
// Split issues into thirds
const issues = JSON.parse(index).issues;
const third = Math.ceil(issues.length / 3);
const batch1 = issues.slice(0, third).map(i => i.key);
const batch2 = issues.slice(third, third * 2).map(i => i.key);
const batch3 = issues.slice(third * 2).map(i => i.key);

// PARALLEL - One message with 3 Task calls
Task({
  subagent_type: "researcher",
  model: "haiku",
  description: "Relevancy Analysis",
  prompt: `Analyze issues ${batch1.concat(batch2).concat(batch3).join(',')} for:
  - Duplicates: search Jira for similar summaries
  - Target exists: Glob/Grep for referenced files in codebase
  Save JSON results to /tmp/garden-analysis/relevancy/`
})

Task({
  subagent_type: "Explore",
  model: "haiku",
  description: "Accuracy Analysis",
  prompt: `Analyze issues ${batch1.concat(batch2).concat(batch3).join(',')} for:
  - Solution drift: compare proposed changes against origin/main
  - Code patterns: do snippets match current codebase?
  Save JSON results to /tmp/garden-analysis/accuracy/`
})

Task({
  subagent_type: "researcher",
  model: "haiku",
  description: "Readiness Analysis",
  prompt: `Analyze issues ${batch1.concat(batch2).concat(batch3).join(',')} for:
  - Dependencies: parse issuelinks and description mentions
  - Sequence position: what must complete before/after
  Save JSON results to /tmp/garden-analysis/readiness/`
})
```

### 3. Collect results and AUTO-APPLY

After agents complete, run the apply script:

```bash
$PROJECT_ROOT/agents/scripts/garden/garden-apply.sh
```

This script automatically:
- **Closes issues** where `recommendation == "close"` or `relevant == false`
- **Adds `fresh-YYYYMMDD` label** to issues where `ready == true`
- **Adds structured comments** with marker prefix to all analyzed issues

Comment format:
```
Garden Analysis: Relevancy

RELEVANT (85% confidence)
- Target exists: true
- No duplicates found
```

### 4. Run Consistency Analysis

```bash
# Dispatch garden-consistency as a subagent
```

```typescript
Task({
  subagent_type: "researcher",
  model: "haiku",
  description: "Consistency Analysis",
  prompt: "Run /garden-consistency to scan PRPs and design sessions for conflicts. Output results to /tmp/garden-analysis/output/consistency-report.json"
})
```

Wait for completion. If consistency-report.json exists, read summary counts.

### 5. Run Consolidation Analysis

```typescript
Task({
  subagent_type: "researcher",
  model: "haiku",
  description: "Consolidation Analysis",
  prompt: "Run /garden-consolidate to find issues that can be batched for a single PR. Output results to /tmp/garden-analysis/output/consolidate-candidates.json"
})
```

Wait for completion. If consolidate-candidates.json exists, read candidate count.

### 6. Write Sequence Manifest to AgentDB

Read the sequence data from the output files:

```bash
sequence_data=$(cat /tmp/garden-analysis/output/sequence.json 2>/dev/null || echo '{"sequence":[]}')
consolidate_data=$(cat /tmp/garden-analysis/output/consolidate-candidates.json 2>/dev/null || echo '{"candidates":[]}')
```

Build the manifest input by merging sequence positions with consolidation candidates:

```bash
# For each issue in sequence.json, add consolidateWith from consolidate-candidates.json
# Then write to AgentDB
```

```bash
# Write manifest via skill
manifest_json=$(python3 -c "
import json, sys
seq = json.load(open('/tmp/garden-analysis/output/sequence.json', 'r'))
cons = json.load(open('/tmp/garden-analysis/output/consolidate-candidates.json', 'r')) if __import__('os').path.exists('/tmp/garden-analysis/output/consolidate-candidates.json') else {'candidates': []}

# Build consolidation map
cons_map = {}
for c in cons.get('candidates', []):
    keyA, keyB = c['keyA'], c['keyB']
    if keyA not in cons_map: cons_map[keyA] = []
    if keyB not in cons_map: cons_map[keyB] = []
    cons_map[keyA].append(keyB)
    cons_map[keyB].append(keyA)

issues = []
for item in seq.get('sequence', []):
    issues.append({
        'key': item['key'],
        'sequencePosition': item.get('sequencePosition', 'anytime'),
        'unblocksCount': len(item.get('unblocks', [])),
        'blockedBy': item.get('blockedBy', []),
        'consolidateWith': cons_map.get(item['key'], [])
    })

result = {
    'issues': issues,
    'generatedAt': seq.get('metadata', {}).get('generatedAt', __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')),
    'issueCount': len(issues)
}
print(json.dumps(result))
" 2>/dev/null || echo '{"issues":[],"generatedAt":"","issueCount":0}')

npx tsx ~/.claude/skills/agentdb/sequence_manifest_write.ts "$manifest_json"
```

**Note**: Only Phase 6 writes to AgentDB. Phases 1-5 write to `/tmp/garden-analysis/` and Jira.

### 7. Review output

The script generates `/tmp/garden-analysis/output/sequence.json`:

```json
{
  "metadata": {
    "version": "1.0",
    "generatedAt": "2026-01-08T14:30:00Z",
    "freshLabel": "fresh-20260108"
  },
  "summary": {
    "closed": 2,
    "labeled": 5,
    "commented": 10,
    "ready": 5,
    "blocked": 3
  },
  "issuesClosed": ["PROJ-100", "PROJ-101"],
  "issuesLabeled": ["PROJ-102", "PROJ-103", "PROJ-104", "PROJ-105", "PROJ-106"],
  "issuesReady": ["PROJ-102", "PROJ-103", "PROJ-104", "PROJ-105", "PROJ-106"],
  "issuesBlocked": ["PROJ-107", "PROJ-108", "PROJ-109"],
  "sequence": [
    {"key": "PROJ-102", "ready": true, "sequencePosition": "early", "blockedBy": [], "unblocks": ["PROJ-105"]},
    {"key": "PROJ-103", "ready": true, "sequencePosition": "early", "blockedBy": [], "unblocks": []},
    {"key": "PROJ-104", "ready": true, "sequencePosition": "middle", "blockedBy": [], "unblocks": ["PROJ-107"]},
    {"key": "PROJ-105", "ready": true, "sequencePosition": "middle", "blockedBy": ["PROJ-102"], "unblocks": []},
    {"key": "PROJ-106", "ready": true, "sequencePosition": "late", "blockedBy": [], "unblocks": []}
  ]
}
```

### 8. Report

Output format:
```
## Garden Analysis Complete

| Analysis | Passed | Issues |
|----------|--------|--------|
| Relevancy | X | PROJ-1, PROJ-2, ... |
| Accuracy | X | PROJ-1, PROJ-2, ... |
| Readiness | X | PROJ-1, PROJ-2, ... |

### Auto-Applied Actions
- Closed: PROJ-100, PROJ-101 (already done/irrelevant)
- Labeled with fresh-20260108: PROJ-102, PROJ-103, PROJ-104, PROJ-105, PROJ-106
- Comments added: 10 issues
- Consistency conflicts found: N (see consistency-report.json)
- Consolidation candidates found: N (see consolidate-candidates.json)
- Sequence manifest written to AgentDB (use /next to see enriched output)

### Issues Ready for To Do
PROJ-102 (early), PROJ-103 (early), PROJ-104 (middle), PROJ-105 (middle), PROJ-106 (late)

### Issues Still Blocked
PROJ-107 (blocked by: PROJ-104)
PROJ-108 (blocked by: PROJ-103, PROJ-105)
PROJ-109 (needs grooming)

### Output Files
- sequence.json: /tmp/garden-analysis/output/sequence.json
```

## Dry Run Mode

To preview actions without making changes:
```bash
$PROJECT_ROOT/agents/scripts/garden/garden-apply.sh --dry-run
```

## Run Subcommands Individually

- `/garden-relevancy` - Only check duplicates and target existence
- `/garden-accuracy` - Only check solution drift
- `/garden-readiness` - Only check dependencies and sequencing
- `/garden-consistency` - Scan PRPs and design sessions for conflicts
- `/garden-consolidate` - Find batching candidates for single-PR delivery
- `/garden-cache` - Refresh the issue cache (including PRPs and design sessions)
- `/sequence-json` - Output machine-readable sequence (no Jira comments)

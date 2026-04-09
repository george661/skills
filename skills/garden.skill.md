# Garden Skill - Backlog Analysis and Auto-Apply

The Garden workflow analyzes Backlog/Grooming issues and automatically applies results to Jira.

## Overview

Garden commands help maintain a healthy backlog by:
1. Detecting duplicate or irrelevant issues
2. Checking if proposed solutions are still accurate
3. Identifying dependencies and sequencing
4. **Automatically applying results** to Jira

## Command Flow

```
/garden-cache     # Step 1: Refresh issue cache (run if stale)
     |
     v
/garden           # Step 2: Full analysis + auto-apply
     |
     +-- /garden-relevancy    # Individual: check duplicates/targets
     +-- /garden-accuracy     # Individual: check solution drift
     +-- /garden-readiness    # Individual: check dependencies
     |
     v
garden-apply.sh   # Step 3: Apply results to Jira (called automatically)
     |
     v
sequence.json     # Output: machine-readable sequence
```

## Automatic Actions

When `/garden` runs, it automatically:

### 1. Closes "Already Done" Issues
Issues are closed when:
- `relevant == false` (target code no longer exists)
- `recommendation == "close"` (duplicate or obsolete)

Comment added: `Garden Analysis: [Type] - Closed by Garden Analysis: [reason]`

### 2. Adds Fresh Labels
Ready issues receive a `fresh-YYYYMMDD` label (e.g., `fresh-20260108`):
- Only issues where `ready == true` and `recommendation == "ready"`
- Label indicates the issue was analyzed on that date

### 3. Adds Garden Comments
All analyzed issues receive structured comments:

```
Garden Analysis: Relevancy

RELEVANT (85% confidence)
- Target exists: true
- Target location: src/components/Example.tsx
- No duplicates found
```

```
Garden Analysis: Accuracy

ACCURATE (90% confidence)
- Compared against: abc1234
- No drift detected
- Recommendation: proceed
```

```
Garden Analysis: Readiness

READY (85% confidence)
- Sequence position: early
- Label added: fresh-20260108
- Unblocks: PROJ-200, PROJ-201
```

## Scripts

### garden-cache.sh
Location: `$PROJECT_ROOT/agents/scripts/garden/garden-cache.sh`

```bash
# Refresh cache (checks TTL, skips if fresh)
./garden-cache.sh

# Force refresh even if fresh
./garden-cache.sh --force

# Use specific .env file
./garden-cache.sh --env /path/to/.env
```

Cache location: `~/.cache/garden/`

### garden-apply.sh
Location: `$PROJECT_ROOT/agents/scripts/garden/garden-apply.sh`

```bash
# Apply all results to Jira
./garden-apply.sh

# Preview changes without applying
./garden-apply.sh --dry-run

# Use specific .env file
./garden-apply.sh --env /path/to/.env
```

## Analysis Result Formats

### Relevancy Result
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

### Accuracy Result
```json
{
  "key": "PROJ-123",
  "accurate": true,
  "confidence": 0.9,
  "proposedSolution": "Add validation to submitForm",
  "currentState": "submitForm exists at src/utils/forms.ts",
  "driftDetails": [],
  "recommendation": "proceed",
  "comparedAgainst": "abc1234"
}
```
Recommendations: `proceed` | `update` | `reassess` | `needs-solution`

### Readiness Result
```json
{
  "key": "PROJ-123",
  "ready": true,
  "confidence": 0.85,
  "mustCompleteBefore": [{"issue": "PROJ-100", "reason": "blocked by", "type": "explicit"}],
  "shouldCompleteAfter": [{"issue": "PROJ-200", "reason": "unblocks", "type": "explicit"}],
  "blockers": [],
  "sequencePosition": "early",
  "recommendation": "ready"
}
```
Recommendations: `ready` | `blocked` | `needs-grooming`

## Output Files

All outputs go to `/tmp/garden-analysis/output/`:

### sequence.json
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
  "issuesLabeled": ["PROJ-102", "PROJ-103"],
  "issuesReady": ["PROJ-102", "PROJ-103", "PROJ-104"],
  "issuesBlocked": ["PROJ-107", "PROJ-108"],
  "sequence": [
    {"key": "PROJ-102", "ready": true, "sequencePosition": "early", "blockedBy": [], "unblocks": ["PROJ-105"]}
  ]
}
```

## Directory Structure

```
~/.cache/garden/
├── issues/
│   ├── index.json      # Issue list with metadata
│   └── PROJ-*.json       # Individual issues
├── active/
│   └── index.json      # To Do, In Progress, Validation
├── analysis/
│   ├── relevancy/
│   ├── accuracy/
│   └── readiness/
└── cache-meta.json     # Timestamp and stats

/tmp/garden-analysis/
├── relevancy/          # Relevancy results
│   └── PROJ-*.json
├── accuracy/           # Accuracy results
│   └── PROJ-*.json
├── readiness/          # Readiness results
│   └── PROJ-*.json
└── output/
    └── sequence.json   # Final output
```

## Integration with /sequence

The garden workflow complements `/sequence`:

| Command | Scope | Auto-Apply | Output |
|---------|-------|------------|--------|
| `/garden` | Backlog/Grooming only | Yes (close, label, comment) | sequence.json |
| `/sequence` | Active issues (To Do, In Progress, Validation) | Yes (Jira comments) | Human report |
| `/sequence-json` | Active issues | No | JSON output |

Use `/garden` to prepare the backlog, then `/sequence` to plan active work.

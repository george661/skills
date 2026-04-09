<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Check if proposed solutions in backlog/grooming issues are still valid against current origin/main.
---

# Garden: Accuracy Analysis

Compares proposed solutions against current `origin/main` to detect drift.

## Prerequisites

Cache must exist at `~/.cache/garden/`. If missing, run `/garden-cache` first.

## Execution

### 1. Setup

```bash
mkdir -p /tmp/garden-analysis/accuracy
```

### 2. Fetch latest from all repos

```bash
cd $PROJECT_ROOT${REPO_FRONTEND} && git fetch origin main
cd $PROJECT_ROOT${REPO_API} && git fetch origin main
cd $PROJECT_ROOT${REPO_AUTH} && git fetch origin main
```

Record commits being compared against:
```bash
git -C $PROJECT_ROOT${REPO_FRONTEND} rev-parse --short origin/main
```

### 3. Load issues from cache

```typescript
const CACHE_DIR = `${process.env.HOME}/.cache/garden`;
const index = JSON.parse(Read(`${CACHE_DIR}/issues/index.json`));
```

### 4. Analyze each issue

**Extract proposed solution from description:**
- Code blocks (```...```)
- File paths mentioned
- "Should" statements
- Implementation sections

**Compare against current code:**
```bash
# Get current file content from origin/main
git show origin/main:path/to/file.ts
```

**Detect drift:**
- File removed/renamed -> `reassess`
- File modified after issue created -> check if changes affect proposal
- Code patterns don't match -> `update`
- No issues found -> `proceed`

### 5. Save results

Per issue, save to `/tmp/garden-analysis/accuracy/{KEY}.json`:
```json
{
  "key": "PROJ-123",
  "accurate": true,
  "confidence": 0.9,
  "proposedSolution": "Add validation to submitForm",
  "currentState": "submitForm exists at src/utils/forms.ts",
  "driftDetails": [],
  "recommendation": "proceed",
  "suggestedUpdates": [],
  "comparedAgainst": "abc1234"
}
```

Recommendations: `proceed` | `update` | `reassess` | `needs-solution`

### 6. Auto-apply results (optional)

Run the apply script to add accuracy comments:
```bash
$PROJECT_ROOT/agents/scripts/garden/garden-apply.sh
```

Or dry-run first:
```bash
$PROJECT_ROOT/agents/scripts/garden/garden-apply.sh --dry-run
```

The script will add comments with marker `Garden Analysis: Accuracy`:

```
Garden Analysis: Accuracy

ACCURATE (90% confidence)
- Compared against: abc1234
- No drift detected
- Recommendation: proceed
```

Or for issues needing update:
```
Garden Analysis: Accuracy

NEEDS UPDATE (60% confidence)
- Compared against: abc1234
- Drift: File structure changed, method signature different
- Recommendation: update
```

### 7. Report

```
## Accuracy Analysis Complete

Compared against origin/main commits:
- ${REPO_FRONTEND}: abc1234
- ${REPO_API}: def5678

| Status | Count |
|--------|-------|
| Accurate | X |
| Needs Update | Y |
| Needs Reassess | Z |

### Auto-Actions Available
Run garden-apply.sh to add comments to all analyzed issues

### Proceed: PROJ-1, PROJ-2
### Update: PROJ-3, PROJ-4
```

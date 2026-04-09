# /review-patterns - Review and Promote Failure Patterns

Review recurring failure patterns detected by the failure-detector hook and
decide whether to promote them to permanent anti-patterns.

## Workflow

### Step 1: Fetch Failure Summary

Call the failure-summary endpoint to get recurring failure patterns that exceed
the promotion threshold:

```bash
npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts '{"task": "failure-summary", "k": 20}'
```

Also call the failure-summary REST endpoint directly:

```python
import json, sys
sys.path.insert(0, str(__import__('pathlib').Path.home() / '.claude' / 'hooks'))
from agentdb_client import agentdb_request
result = agentdb_request('POST', '/api/v1/reflexion/failure-summary', {'threshold': 3})
```

### Step 2: Display Candidates

For each candidate, display:
- **Type**: The failure signature type (e.g., `aws-token-expired`, `wrong-cwd-skill`)
- **Count**: Number of times this failure has occurred
- **Date Range**: First occurrence to most recent
- **Example Commands**: Sample commands that triggered this failure
- **Suggested Fix**: The recommended remediation

Format as a numbered list for easy reference.

### Step 3: User Decision

For each candidate, ask the user to choose one of:

1. **Promote** - Create a permanent anti-pattern from this failure pattern
2. **Dismiss** - Mark this failure pattern as reviewed but not worth promoting
3. **Skip** - Leave for later review

### Step 4: Process Decisions

**For Promoted patterns:**

Store as a new anti-pattern with success_rate 0.0:

```bash
npx tsx ~/.claude/skills/agentdb/pattern_store.ts '{"task_type": "anti-pattern-<type>", "approach": "<suggested_fix>", "success_rate": 0.0, "tags": ["promoted", "anti-pattern"]}'
```

**For Dismissed patterns:**

Store a reflexion episode noting the dismissal so the pattern is not
re-surfaced in future reviews:

```bash
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{"session_id": "${TENANT_NAMESPACE}", "task": "review-patterns-dismiss: <type>", "reward": 0.5, "success": true, "critique": "Dismissed by user review - not significant enough to promote"}'
```

### Step 5: Refresh Cache

After processing all decisions, refresh the local anti-pattern cache so the
pattern-guard hook picks up any newly promoted patterns:

```python
import json, os, sys
sys.path.insert(0, str(__import__('pathlib').Path.home() / '.claude' / 'hooks'))
from agentdb_client import agentdb_request
result = agentdb_request('POST', '/api/v1/pattern/search', {'task': 'anti-pattern', 'k': 50, 'weighted': True})
if result:
    anti_patterns = [r for r in result.get('results', []) if r.get('success_rate', 1.0) <= 0.5]
    cache_dir = os.path.expanduser('~/.claude/cache')
    os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, 'anti-patterns.json'), 'w') as f:
        json.dump(anti_patterns, f, indent=2)
```

### Step 6: Report Results

Summarize the review session:
- Number of candidates reviewed
- Number promoted to anti-patterns
- Number dismissed
- Number skipped for later

## Notes

- This command is typically run when `pattern-scorer.py` reports promotion
  candidates at session start
- Patterns promoted here will immediately be enforced by `pattern-guard.py`
  on subsequent tool calls
- Dismissed patterns will not be re-surfaced unless they accumulate
  significantly more occurrences

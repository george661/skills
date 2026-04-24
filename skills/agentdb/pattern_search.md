---
name: agentdb:pattern_search
description: Search for reasoning patterns by task similarity
---

# pattern_search

Searches for stored reasoning patterns based on task similarity using semantic search. Returns patterns that have been successful for similar tasks in the past.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task` | string | Yes | The task description to search for similar patterns |
| `k` | number | Yes | Maximum number of results to return |
| `threshold` | number | No | Minimum similarity threshold (0-1) for results |
| `filters` | Record<string, unknown> | No | Additional filters to apply to the search |

## Example

```typescript
// Search for patterns related to code review tasks
npx tsx ~/.claude/skills/agentdb/pattern_search.ts '{"task": "review pull request for security issues", "k": 5}'

// Search with similarity threshold
npx tsx ~/.claude/skills/agentdb/pattern_search.ts '{"task": "fix failing unit tests", "k": 3, "threshold": 0.7}'

// Search with filters
npx tsx ~/.claude/skills/agentdb/pattern_search.ts '{"task": "implement API endpoint", "k": 5, "filters": {"tags": ["backend"]}}'
```

## Notes

- Uses vector similarity search to find relevant patterns
- Higher `k` values return more results but may include less relevant patterns
- Use `threshold` to filter out low-quality matches
- Patterns are stored via `pattern_store` and include task type, approach, and success rate
- Requires agentdb to be configured as SSE in `~/.claude/settings.json`

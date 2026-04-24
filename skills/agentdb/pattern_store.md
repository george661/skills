---
name: agentdb:pattern_store
description: Store a reasoning pattern with task type, approach, and success rate
---

# pattern_store

Stores a reasoning pattern in agentdb for future retrieval. Patterns capture successful approaches to specific task types along with their success rates.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task_type` | string | Yes | Category or type of task this pattern applies to |
| `approach` | string | Yes | Description of the approach or strategy used |
| `success_rate` | number | Yes | Success rate of this approach (0-1) |
| `metadata` | Record<string, unknown> | No | Additional metadata to store with the pattern |
| `tags` | string[] | No | Tags for categorizing and filtering patterns |

## Example

```typescript
// Store a successful code review pattern
npx tsx ~/.claude/skills/agentdb/pattern_store.ts '{"task_type": "code_review", "approach": "Check for SQL injection vulnerabilities in user input handling", "success_rate": 0.95}'

// Store with metadata and tags
npx tsx ~/.claude/skills/agentdb/pattern_store.ts '{"task_type": "bug_fix", "approach": "Start with failing test, trace execution path, fix root cause", "success_rate": 0.85, "metadata": {"language": "typescript"}, "tags": ["tdd", "debugging"]}'
```

## Notes

- Patterns are searchable via `pattern_search` using semantic similarity
- Use descriptive `task_type` values for better pattern organization
- `success_rate` should reflect observed success across multiple instances
- Tags enable filtering during search operations
- Requires agentdb to be configured as SSE in `~/.claude/settings.json`

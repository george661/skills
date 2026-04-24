---
name: agentdb:reflexion_retrieve_relevant
description: Semantic search for relevant past episodes
---

# reflexion_retrieve_relevant

Performs semantic search to retrieve relevant past episodes from the reflexion memory. Use this to find similar past experiences before attempting a new task.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task` | string | Yes | The current task description to find relevant episodes for |
| `k` | number | Yes | Maximum number of episodes to return |
| `threshold` | number | No | Minimum similarity threshold (0-1) for results |
| `filters` | Record<string, unknown> | No | Additional filters to apply to the search |

## Example

```typescript
// Retrieve episodes related to a deployment task
npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts '{"task": "deploy Lambda function to AWS", "k": 5}'

// Retrieve with similarity threshold
npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts '{"task": "fix TypeScript compilation error", "k": 3, "threshold": 0.8}'

// Retrieve with filters for successful episodes only
npx tsx ~/.claude/skills/agentdb/reflexion_retrieve_relevant.ts '{"task": "implement REST API", "k": 5, "filters": {"success": true}}'
```

## Notes

- Part of the Reflexion learning system for agents
- Returns episodes with their critiques and outcomes
- Use before attempting tasks to learn from past successes and failures
- Episodes are stored via `reflexion_store_episode`
- Higher threshold values return more similar but fewer results
- Requires agentdb to be configured as SSE in `~/.claude/settings.json`

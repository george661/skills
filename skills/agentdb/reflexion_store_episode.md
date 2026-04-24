---
name: agentdb:reflexion_store_episode
description: Store a session episode with task, reward, success status, and critique
---

# reflexion_store_episode

Stores a session episode in the reflexion memory system. Episodes capture task attempts with their outcomes, enabling agents to learn from past experiences.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | Yes | Unique identifier for the session |
| `task` | string | Yes | Description of the task attempted |
| `reward` | number | Yes | Reward score for the outcome (-1 to 1 typical) |
| `success` | boolean | Yes | Whether the task completed successfully |
| `critique` | string | No | Self-reflection or analysis of the attempt |
| `input` | string | No | The input provided for the task |
| `output` | string | No | The output produced by the task |
| `latency_ms` | number | No | Time taken to complete the task in milliseconds |
| `tokens_used` | number | No | Number of tokens consumed during the task |

## Example

```typescript
// Store a successful episode
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{"session_id": "session-123", "task": "implement user authentication", "reward": 1.0, "success": true, "critique": "Used JWT tokens with proper expiration handling"}'

// Store a failed episode with detailed critique
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{"session_id": "session-124", "task": "optimize database query", "reward": -0.5, "success": false, "critique": "Index was missing on frequently queried column", "latency_ms": 5000}'

// Store with full details
npx tsx ~/.claude/skills/agentdb/reflexion_store_episode.ts '{"session_id": "session-125", "task": "fix CI pipeline", "reward": 1.0, "success": true, "critique": "Root cause was missing environment variable", "input": "Pipeline failing on test step", "output": "Added NODE_ENV to pipeline config", "latency_ms": 120000, "tokens_used": 15000}'
```

## Notes

- Part of the Reflexion learning system for agents
- Episodes are retrievable via `reflexion_retrieve_relevant`
- Include detailed critiques for better learning from failures
- Use consistent session IDs to group related episodes
- `reward` values typically range from -1 (complete failure) to 1 (complete success)
- Performance metrics (`latency_ms`, `tokens_used`) help identify efficiency patterns
- Requires agentdb to be configured as SSE in `~/.claude/settings.json`

---
name: concourse:list_pipelines
description: List all pipelines for the configured Concourse team.
---

# list_pipelines

List all pipelines for the configured Concourse team. Use this to discover available pipelines and their current status.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| (none) | - | - | Team is loaded from credentials configuration |

## Example

```typescript
// List all pipelines for the team
npx tsx ~/.claude/skills/concourse/list_pipelines.ts '{}'
```

## Notes

- The team name is loaded from credentials (CONCOURSE_TEAM)
- Returns an array of pipeline objects with name, paused status, and team info
- Pipeline states include paused and unpaused

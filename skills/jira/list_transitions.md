---
name: jira:list_transitions
description: List available transitions for an issue (workflow states it can move to).
---

# list_transitions

List all available workflow transitions for a specific issue. These are the states the issue can move to from its current status.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `issue_key` | string | Yes | The issue key (e.g., "PROJ-123") |

## Example

```typescript
// List available transitions for an issue
npx tsx ~/.claude/skills/jira/list_transitions.ts '{"issue_key": "PROJ-123"}'
```

## Notes

- Returns transition IDs and names based on the issue's current status
- Use the transition ID with `transition_issue` to move the issue
- Available transitions depend on the project's workflow configuration

---
name: jira:get_sprint
description: Get details about a specific sprint.
---

# get_sprint

Get detailed information about a specific sprint, including its name, state, and dates.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sprint_id` | number | Yes | The sprint ID |

## Example

```typescript
// Get sprint details
npx tsx ~/.claude/skills/jira/get_sprint.ts '{"sprint_id": 42}'
```

## Notes

- Use `list_sprints` to find sprint IDs for a board
- Returns sprint name, state (active, closed, future), start date, and end date

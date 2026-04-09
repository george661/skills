---
name: jira:get_worklogs
description: Get all worklogs for an issue.
---

# get_worklogs

Get all worklog entries for a specific Jira issue, showing time spent and work descriptions.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `issue_key` | string | Yes | The issue key (e.g., "PROJ-123") |

## Example

```typescript
// Get all worklogs for an issue
npx tsx ~/.claude/skills/jira/get_worklogs.ts '{"issue_key": "PROJ-123"}'
```

## Notes

- Returns all worklog entries including time spent, author, and comments
- Useful for time tracking and project reporting

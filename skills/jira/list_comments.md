---
name: jira:list_comments
description: List all comments on an issue.
---

# list_comments

List all comments on a specific Jira issue.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `issue_key` | string | Yes | The issue key (e.g., "PROJ-123") |

## Example

```typescript
// List all comments on an issue
npx tsx ~/.claude/skills/jira/list_comments.ts '{"issue_key": "PROJ-123"}'
```

## Notes

- Returns comments in chronological order
- Each comment includes the author, body, and creation date
- Use comment IDs from results with `update_comment` or `delete_comment`

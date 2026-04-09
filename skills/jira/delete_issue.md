---
name: jira:delete_issue
description: Delete an issue from Jira. Use with caution.
---

# delete_issue

Delete an issue from Jira permanently. This action cannot be undone.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `issue_key` | string | Yes | The issue key (e.g., "PROJ-123") |

## Example

```typescript
// Delete an issue
npx tsx ~/.claude/skills/jira/delete_issue.ts '{"issue_key": "PROJ-123"}'
```

## Notes

- This action is permanent and cannot be undone
- All comments, worklogs, and attachments will also be deleted
- You must have delete permissions for the issue
- Consider closing or archiving issues instead of deleting them

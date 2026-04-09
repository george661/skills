---
name: jira:delete_comment
description: Delete a comment from an issue.
---

# delete_comment

Delete a comment from a Jira issue. Use with caution as this action cannot be undone.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `issue_key` | string | Yes | The issue key (e.g., "PROJ-123") |
| `comment_id` | string | Yes | The comment ID to delete |

## Example

```typescript
// Delete a comment
npx tsx ~/.claude/skills/jira/delete_comment.ts '{"issue_key": "PROJ-123", "comment_id": "10001"}'
```

## Notes

- Use `list_comments` to get comment IDs for an issue
- This action is permanent and cannot be undone
- You can only delete comments you have permission to delete

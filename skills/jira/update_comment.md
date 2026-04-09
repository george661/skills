---
name: jira:update_comment
description: Update an existing comment.
---

# update_comment

Update the content of an existing comment on a Jira issue.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `issue_key` | string | Yes | The issue key (e.g., "PROJ-123") |
| `comment_id` | string | Yes | The comment ID to update |
| `body` | string | Yes | New comment body (supports Jira markdown) |

## Example

```typescript
// Update a comment
npx tsx ~/.claude/skills/jira/update_comment.ts '{"issue_key": "PROJ-123", "comment_id": "10001", "body": "Updated comment content"}'
```

## Notes

- Use `list_comments` to get comment IDs for an issue
- The body field supports Jira markdown formatting
- You can only update comments you have permission to edit

---
name: jira:add_comment
description: Add a comment to an issue.
---

# add_comment

Add a comment to a Jira issue. This is useful for providing updates, asking questions, or documenting progress on an issue.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `issue_key` | string | Yes | The issue key (e.g., "PROJ-123") |
| `body` | string | Yes | Comment body (supports Jira markdown) |

## Example

```typescript
// Add a simple comment to an issue
npx tsx ~/.claude/skills/jira/add_comment.ts '{"issue_key": "PROJ-123", "body": "This is a comment"}'

// Add a formatted comment with markdown
npx tsx ~/.claude/skills/jira/add_comment.ts '{"issue_key": "PROJ-123", "body": "## Update\n\nWork has been completed on this task.\n\n* Item 1\n* Item 2"}'
```

## Notes

- The body field supports Jira markdown formatting
- Comments are visible to anyone with access to the issue
- Use this to document implementation progress or provide status updates

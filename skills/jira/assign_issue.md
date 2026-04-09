---
name: jira:assign_issue
description: Assign or unassign an issue to a user.
---

# assign_issue

Assign a Jira issue to a specific user, or unassign it by omitting the account ID.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `issue_key` | string | Yes | The issue key (e.g., "PROJ-123") |
| `account_id` | string | No | Account ID of the assignee, or omit to unassign |

## Example

```typescript
// Assign an issue to a user
npx tsx ~/.claude/skills/jira/assign_issue.ts '{"issue_key": "PROJ-123", "account_id": "5b10ac8d82e05b22cc7d4ef5"}'

// Unassign an issue
npx tsx ~/.claude/skills/jira/assign_issue.ts '{"issue_key": "PROJ-123"}'
```

## Notes

- Use `search_users` to find a user's account ID
- Use `get_current_user` to get your own account ID
- Omitting `account_id` will unassign the issue from any current assignee

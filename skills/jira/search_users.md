---
name: jira:search_users
description: Search for users by name or email.
---

# search_users

Search for Jira users by name or email address.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search query (name or email) |
| `start_at` | number | No | Starting index for pagination (default: 0) |
| `max_results` | number | No | Maximum results to return |

## Example

```typescript
// Search for a user by name
npx tsx ~/.claude/skills/jira/search_users.ts '{"query": "John"}'

// Search for a user by email
npx tsx ~/.claude/skills/jira/search_users.ts '{"query": "john.doe@example.com"}'
```

## Notes

- Returns user account IDs, display names, and email addresses
- Use the account ID from results with `assign_issue` and `create_issue`
- Partial matches are supported

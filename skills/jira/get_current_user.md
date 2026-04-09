---
name: jira:get_current_user
description: Get information about the currently authenticated user.
---

# get_current_user

Get information about the currently authenticated Jira user, including account ID, display name, and email.

## Parameters

This function takes no parameters.

## Example

```typescript
// Get current user information
npx tsx ~/.claude/skills/jira/get_current_user.ts '{}'
```

## Notes

- Useful for getting your account ID for issue assignment
- Returns display name, email address, and account ID
- The account ID can be used with `assign_issue` and `create_issue`

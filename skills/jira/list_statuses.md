---
name: jira:list_statuses
description: List all available issue statuses.
---

# list_statuses

List all available issue statuses in the Jira instance.

## Parameters

This function takes no parameters.

## Example

```typescript
// List all statuses
npx tsx ~/.claude/skills/jira/list_statuses.ts '{}'
```

## Notes

- Returns all statuses including their names and categories
- Common statuses: To Do, In Progress, Done, Blocked
- Status categories: To Do, In Progress, Done

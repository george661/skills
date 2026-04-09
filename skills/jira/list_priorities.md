---
name: jira:list_priorities
description: List all available priority levels.
---

# list_priorities

List all available priority levels in the Jira instance.

## Parameters

This function takes no parameters.

## Example

```typescript
// List all priorities
npx tsx ~/.claude/skills/jira/list_priorities.ts '{}'
```

## Notes

- Returns all priority levels including their names and icons
- Use the priority name when creating or updating issues
- Common priorities: Highest, High, Medium, Low, Lowest

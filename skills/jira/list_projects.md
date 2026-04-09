---
name: jira:list_projects
description: List all configured Jira projects. Returns project details including key, name, and type.
---

# list_projects

List all Jira projects accessible to the authenticated user, including project keys, names, and types.

## Parameters

This function takes no parameters.

## Example

```typescript
// List all projects
npx tsx ~/.claude/skills/jira/list_projects.ts '{}'
```

## Notes

- Returns all projects you have permission to view
- Each project includes its key, name, and project type
- Use the project key when creating issues or searching

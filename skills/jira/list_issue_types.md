---
name: jira:list_issue_types
description: List all available issue types.
---

# list_issue_types

List all available issue types in the Jira instance (e.g., Bug, Story, Task, Epic).

## Parameters

This function takes no parameters.

## Example

```typescript
// List all issue types
npx tsx ~/.claude/skills/jira/list_issue_types.ts '{}'
```

## Notes

- Returns all issue types including their names, descriptions, and icons
- Use the issue type name when creating issues with `create_issue`
- Common types: Bug, Story, Task, Epic, Sub-task

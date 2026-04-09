---
name: jira:add_issue_to_sprint
description: Add an issue to a sprint.
---

# add_issue_to_sprint

Add a Jira issue to a specific sprint. This is used for sprint planning and organizing work into iterations.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `issue_key` | string | Yes | The issue key (e.g., "PROJ-123") |
| `sprint_id` | number | Yes | The sprint ID to add the issue to |

## Example

```typescript
// Add an issue to sprint 42
npx tsx ~/.claude/skills/jira/add_issue_to_sprint.ts '{"issue_key": "PROJ-123", "sprint_id": 42}'
```

## Notes

- You can get sprint IDs using the `list_sprints` function
- Issues can only be in one sprint at a time
- Moving an issue to a different sprint will remove it from the current sprint

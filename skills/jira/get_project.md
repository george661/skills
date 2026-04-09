---
name: jira:get_project
description: Get detailed information about a specific Jira project.
---

# get_project

Get detailed information about a specific Jira project, including its key, name, lead, and configuration.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_key` | string | Yes | The project key (e.g., "PROJ") |

## Example

```typescript
// Get project details
npx tsx ~/.claude/skills/jira/get_project.ts '{"project_key": "PROJ"}'
```

## Notes

- Returns project name, key, description, lead, and project type
- Use `list_projects` to see all available projects

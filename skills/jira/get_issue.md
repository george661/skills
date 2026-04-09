---
name: jira:get_issue
description: Get detailed information about a specific issue by its key.
---

# get_issue

Get detailed information about a specific Jira issue by its key. Use the `fields` parameter to request only needed data for better performance.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `issue_key` | string | Yes | The issue key (e.g., "PROJ-123") |
| `fields` | string | No | Comma-separated list of fields to return (e.g., "summary,status,assignee") |
| `expand` | string | No | Comma-separated list of entities to expand (e.g., "changelog,renderedFields") |

## Example

```typescript
// Get full issue details
npx tsx ~/.claude/skills/jira/get_issue.ts '{"issue_key": "PROJ-123"}'

// Get specific fields only
npx tsx ~/.claude/skills/jira/get_issue.ts '{"issue_key": "PROJ-123", "fields": "summary,status,assignee,priority"}'

// Get issue with changelog
npx tsx ~/.claude/skills/jira/get_issue.ts '{"issue_key": "PROJ-123", "expand": "changelog"}'
```

## Notes

- Use `fields` parameter to reduce response size and improve performance
- Common fields: summary, status, assignee, reporter, priority, description, labels
- The `expand` parameter can include: changelog, renderedFields, transitions, operations

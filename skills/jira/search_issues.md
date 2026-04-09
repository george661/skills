---
name: jira:search_issues
description: Search for issues using JQL (Jira Query Language). Returns paginated results.
---

# search_issues

Search for Jira issues using JQL (Jira Query Language). Returns paginated results with configurable field selection.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `jql` | string | Yes | JQL query string (e.g., "project = PROJ AND status = Open") |
| `start_at` | number | No | Starting index for pagination (default: 0) |
| `max_results` | number | No | Maximum number of results to return (default: 50, max: 100) |
| `fields` | string[] | No | List of fields to return (e.g., ["summary", "status", "assignee"]) |

## Example

```typescript
// Search for open issues in a project
npx tsx ~/.claude/skills/jira/search_issues.ts '{"jql": "project = PROJ AND status = Open"}'

// Search with specific fields for better performance
npx tsx ~/.claude/skills/jira/search_issues.ts '{"jql": "project = PROJ AND assignee = currentUser()", "fields": ["key", "summary", "status", "priority"]}'

// Paginated search
npx tsx ~/.claude/skills/jira/search_issues.ts '{"jql": "project = PROJ", "start_at": 50, "max_results": 25}'
```

## Notes

- Always use the `fields` parameter to reduce response size and improve performance
- JQL supports complex queries with AND, OR, ORDER BY, and functions like currentUser()
- Common JQL fields: project, status, assignee, reporter, priority, labels, created, updated
- Maximum of 100 results per request; use pagination for larger result sets

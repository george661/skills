---
name: jira:get_sprint_issues
description: Get all issues in a sprint.
---

# get_sprint_issues

Get all issues in a specific sprint, with optional filtering and field selection.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `board_id` | number | Yes | The board ID |
| `sprint_id` | number | Yes | The sprint ID |
| `jql` | string | No | Additional JQL filter |
| `start_at` | number | No | Starting index for pagination (default: 0) |
| `max_results` | number | No | Maximum results to return |
| `fields` | string | No | Comma-separated list of fields to return |

## Example

```typescript
// Get all issues in a sprint
npx tsx ~/.claude/skills/jira/get_sprint_issues.ts '{"board_id": 1, "sprint_id": 42}'

// Get sprint issues with specific fields
npx tsx ~/.claude/skills/jira/get_sprint_issues.ts '{"board_id": 1, "sprint_id": 42, "fields": "summary,status,assignee"}'

// Filter sprint issues by status
npx tsx ~/.claude/skills/jira/get_sprint_issues.ts '{"board_id": 1, "sprint_id": 42, "jql": "status = \"In Progress\""}'
```

## Notes

- Use `fields` parameter to reduce response size
- The `jql` parameter allows additional filtering within the sprint
- Results are paginated; use `start_at` and `max_results` for large sprints

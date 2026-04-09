---
name: jira:update_issue
description: Update an existing issue. Only provide fields you want to change.
---

# update_issue

Update an existing Jira issue. Only provide the fields you want to change; omitted fields remain unchanged.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `issue_key` | string | Yes | The issue key (e.g., "PROJ-123") |
| `summary` | string | No | New summary/title |
| `description` | string | No | New description (supports Jira markdown) |
| `priority` | string | No | New priority name (e.g., "High", "Medium", "Low") |
| `labels` | string[] | No | New list of labels (replaces existing) |
| `parent` | string | No | Parent issue key (e.g., "PROJ-100") to set as parent Epic or Story |
| `cost` | number | No | Estimated or actual cost (only applied if `JIRA_COST_FIELD_ID` is set in tenant config) |
| `notify_users` | boolean | No | Whether to send email notification (default: true) |

## Example

```typescript
// Update issue summary
npx tsx ~/.claude/skills/jira/update_issue.ts '{"issue_key": "PROJ-123", "summary": "Updated title"}'

// Update multiple fields
npx tsx ~/.claude/skills/jira/update_issue.ts '{"issue_key": "PROJ-123", "summary": "New title", "priority": "High", "labels": ["urgent", "bug"]}'

// Update cost (requires JIRA_COST_FIELD_ID in tenant config)
npx tsx ~/.claude/skills/jira/update_issue.ts '{"issue_key": "PROJ-123", "cost": 150.00}'

// Update without notifications (for automation)
npx tsx ~/.claude/skills/jira/update_issue.ts '{"issue_key": "PROJ-123", "description": "Updated description", "notify_users": false}'
```

## Notes

- Only include fields you want to change
- Labels array replaces all existing labels; include all desired labels
- Set `notify_users: false` for automated updates to avoid spamming users
- Use `transition_issue` to change issue status, not this function
- `cost` is silently ignored if `JIRA_COST_FIELD_ID` is not configured in the tenant `.env`

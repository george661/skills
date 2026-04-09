---
name: jira:create_issue
description: Create a new issue in Jira.
---

# create_issue

Create a new issue in a Jira project. Supports various issue types including Bug, Story, Task, and Epic.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_key` | string | Yes | The project key (e.g., "PROJ") |
| `summary` | string | Yes | Issue summary/title |
| `issue_type` | string | Yes | Issue type name (e.g., "Bug", "Story", "Task", "Epic") |
| `description` | string | No | Issue description (supports Jira markdown) |
| `priority` | string | No | Priority name (e.g., "High", "Medium", "Low") |
| `assignee_account_id` | string | No | Account ID of the assignee |
| `labels` | string[] | No | List of labels to add to the issue |
| `parent` | string | No | Parent issue key (e.g., "PROJ-100") to create under an Epic or Story |
| `cost` | number | No | Estimated or actual cost (only applied if `JIRA_COST_FIELD_ID` is set in tenant config) |
| `notify_users` | boolean | No | Whether to send email notification (default: true) |

## Example

```typescript
// Create a simple task
npx tsx ~/.claude/skills/jira/create_issue.ts '{"project_key": "PROJ", "summary": "Implement feature X", "issue_type": "Task"}'

// Create a bug with full details
npx tsx ~/.claude/skills/jira/create_issue.ts '{"project_key": "PROJ", "summary": "Login button not working", "issue_type": "Bug", "description": "## Steps to Reproduce\n\n1. Go to login page\n2. Click login button\n3. Nothing happens", "priority": "High", "labels": ["bug", "urgent"]}'

// Create a story under an epic with cost
npx tsx ~/.claude/skills/jira/create_issue.ts '{"project_key": "PROJ", "summary": "User authentication", "issue_type": "Story", "parent": "PROJ-100", "cost": 250.00}'
```

## Notes

- Use `list_issue_types` to see available issue types
- Use `list_priorities` to see available priority levels
- Set `notify_users: false` for automation to avoid spamming users
- `cost` is silently ignored if `JIRA_COST_FIELD_ID` is not configured in the tenant `.env`

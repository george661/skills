# create_issue

Create new issues in Jira. Use `parent` to link to epics.

## Required Parameters

- `project_key` - Project identifier (e.g., "${PROJECT_KEY}")
- `summary` - Issue title
- `issue_type` - "Task", "Bug", "Story", "Epic", "Sub-task"

## Examples

### Create task under an epic
```bash
npx tsx .claude/skills/jira-mcp/create_issue.ts '{"project_key": "${PROJECT_KEY}", "summary": "Implement JWT token validation", "issue_type": "Task", "description": "Add JWT validation middleware to protect API endpoints.", "parent": "PROJ-100", "priority": "High", "labels": ["backend", "security"], "notify_users": false}'
```

### Create bug report
```bash
npx tsx .claude/skills/jira-mcp/create_issue.ts '{"project_key": "${PROJECT_KEY}", "summary": "Login fails with special characters in password", "issue_type": "Bug", "description": "## Steps to Reproduce\n1. Create account with password containing &\n2. Attempt login\n3. Observe 500 error\n\n## Expected\nSuccessful login\n\n## Actual\nServer error returned", "priority": "Critical", "labels": ["auth", "urgent"], "notify_users": false}'
```

### Create story
```bash
npx tsx .claude/skills/jira-mcp/create_issue.ts '{"project_key": "${PROJECT_KEY}", "summary": "User can reset password via email", "issue_type": "Story", "description": "As a user who forgot my password, I want to reset it via email so I can regain access to my account.", "parent": "PROJ-50", "notify_users": false}'
```

## Return Format

```json
{
  "id": "10234",
  "key": "PROJ-124",
  "self": "https://your-domain.atlassian.net/rest/api/3/issue/10234"
}
```

## Notes

- `parent` links to Epic for Task/Story/Bug
- `parent` links to Story for Sub-task
- Description supports Jira markdown
- Labels must already exist in project
- `assignee_account_id` requires user's Atlassian account ID

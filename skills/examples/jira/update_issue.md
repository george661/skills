# update_issue

Update fields on an existing issue. Only provide fields you want to change.

## Parameters

- `issue_key` - Issue identifier (required)
- All other fields are optional

## Examples

### Update summary and description
```bash
npx tsx .claude/skills/jira-mcp/update_issue.ts '{"issue_key": "PROJ-123", "summary": "Implement JWT validation with refresh tokens", "description": "Updated requirements:\n\n- Validate access tokens\n- Support refresh token rotation\n- Add token blacklist for logout", "notify_users": false}'
```

### Change priority
```bash
npx tsx .claude/skills/jira-mcp/update_issue.ts '{"issue_key": "PROJ-123", "priority": "Critical", "notify_users": false}'
```

### Update labels
```bash
npx tsx .claude/skills/jira-mcp/update_issue.ts '{"issue_key": "PROJ-123", "labels": ["backend", "security", "sprint-12"], "notify_users": false}'
```

### Move to different epic
```bash
npx tsx .claude/skills/jira-mcp/update_issue.ts '{"issue_key": "PROJ-123", "parent": "PROJ-200", "notify_users": false}'
```

### Combined update
```bash
npx tsx .claude/skills/jira-mcp/update_issue.ts '{"issue_key": "PROJ-123", "summary": "Updated title", "priority": "High", "labels": ["urgent", "backend"], "description": "New detailed description here", "notify_users": false}'
```

## Updatable Fields

| Field | Type | Notes |
|-------|------|-------|
| `summary` | string | Issue title |
| `description` | string | Full description |
| `priority` | string | "Highest", "High", "Medium", "Low", "Lowest" |
| `labels` | array | Replaces all existing labels |
| `parent` | string | Epic key (e.g., "PROJ-100") |

## Return Format

Returns empty on success (HTTP 204). Use `get_issue` to verify changes.

## Notes

- Labels array **replaces** existing labels (not additive)
- To add a label, first get current labels, then update with full list
- Cannot update `status` directly - use `transition_issue` instead
- Cannot update `issuetype` after creation

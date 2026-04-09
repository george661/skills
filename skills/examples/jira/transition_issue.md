# transition_issue

Move an issue to a new status. Requires transition ID (not status name).

## Getting Transition IDs

First, list available transitions:
```bash
npx tsx .claude/skills/jira-mcp/list_transitions.ts '{"issue_key": "PROJ-123"}'
```

Returns:
```json
{
  "transitions": [
    { "id": "11", "name": "To Do" },
    { "id": "21", "name": "In Progress" },
    { "id": "31", "name": "In Review" },
    { "id": "41", "name": "Done" }
  ]
}
```

## Examples

### Start work on issue
```bash
npx tsx .claude/skills/jira-mcp/transition_issue.ts '{"issue_key": "PROJ-123", "transition_id": "21", "comment": "Starting implementation", "notify_users": false}'
```

### Move to review
```bash
npx tsx .claude/skills/jira-mcp/transition_issue.ts '{"issue_key": "PROJ-123", "transition_id": "31", "comment": "Ready for code review. PR: https://bitbucket.org/...", "notify_users": false}'
```

### Complete issue
```bash
npx tsx .claude/skills/jira-mcp/transition_issue.ts '{"issue_key": "PROJ-123", "transition_id": "41", "comment": "Deployed and verified in staging", "notify_users": false}'
```

### Silent transition (no notification)
```bash
npx tsx .claude/skills/jira-mcp/transition_issue.ts '{"issue_key": "PROJ-123", "transition_id": "21", "notify_users": false}'
```

## Common Transition IDs

**Note:** These vary by project workflow. Always use `list_transitions` first.

| Typical Name | Common ID |
|--------------|-----------|
| To Do | 11 |
| In Progress | 21 |
| In Review | 31 |
| Done | 41 |

## Return Format

Returns empty on success (HTTP 204). Check with `get_issue` to confirm.

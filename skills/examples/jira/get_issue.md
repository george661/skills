# get_issue

Retrieve details for a single issue. Use `fields` to limit response size.

## Field Selection

**Quick status check:**
```
fields: "key,summary,status"
```

**For implementation work:**
```
fields: "summary,description,status,priority,issuetype,parent"
```

**Full context with comments:**
```
fields: "summary,description,status,priority,comment"
expand: "renderedFields"
```

## Examples

### Basic issue fetch
```bash
npx tsx .claude/skills/jira-mcp/get_issue.ts '{"issue_key": "PROJ-123", "fields": "summary,status,priority,description"}'
```

### With rendered description (HTML)
```bash
npx tsx .claude/skills/jira-mcp/get_issue.ts '{"issue_key": "PROJ-123", "fields": "summary,description,status", "expand": "renderedFields"}'
```

### Get issue with changelog
```bash
npx tsx .claude/skills/jira-mcp/get_issue.ts '{"issue_key": "PROJ-123", "fields": "summary,status", "expand": "changelog"}'
```

## Return Format

```json
{
  "key": "PROJ-123",
  "fields": {
    "summary": "Implement user authentication",
    "status": { "name": "In Progress" },
    "priority": { "name": "High" },
    "description": "As a user, I want to...",
    "issuetype": { "name": "Story" },
    "parent": { "key": "PROJ-100" }
  }
}
```

## Common Field Names

| Field | Returns |
|-------|---------|
| `summary` | Issue title |
| `description` | Full description text |
| `status` | Current status object |
| `priority` | Priority level |
| `assignee` | Assigned user |
| `reporter` | Creator |
| `parent` | Parent epic/story |
| `comment` | Comments array |
| `labels` | Label strings |
| `created` | Creation timestamp |
| `updated` | Last update timestamp |

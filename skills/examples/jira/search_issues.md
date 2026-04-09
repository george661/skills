# search_issues

Search for issues using JQL. Always use `fields` parameter to reduce response size.

## Field Selection

**Minimal fields for list views:**
```
["key", "summary", "status"]
```

**Standard fields for work selection:**
```
["key", "summary", "status", "priority", "assignee", "issuetype"]
```

**With parent info (for subtasks):**
```
["key", "summary", "status", "priority", "parent"]
```

## Examples

### Find open issues in a project
```bash
npx tsx .claude/skills/jira-mcp/search_issues.ts '{"jql": "project = ${TENANT_PROJECT} AND status != Done ORDER BY priority DESC", "fields": ["key", "summary", "status", "priority"], "max_results": 20}'
```

### Find issues in a sprint
```bash
npx tsx .claude/skills/jira-mcp/search_issues.ts '{"jql": "sprint in openSprints() AND assignee = currentUser()", "fields": ["key", "summary", "status", "issuetype"], "max_results": 50}'
```

### Find bugs by priority
```bash
npx tsx .claude/skills/jira-mcp/search_issues.ts '{"jql": "project = ${TENANT_PROJECT} AND issuetype = Bug AND status != Done ORDER BY priority DESC", "fields": ["key", "summary", "status", "priority", "created"], "max_results": 25}'
```

## Return Format

```json
{
  "issues": [
    {
      "key": "PROJ-123",
      "fields": {
        "summary": "Issue title",
        "status": { "name": "In Progress" },
        "priority": { "name": "High" }
      }
    }
  ],
  "total": 45,
  "startAt": 0,
  "maxResults": 20
}
```

## Common JQL Patterns

| Pattern | JQL |
|---------|-----|
| My open work | `assignee = currentUser() AND status != Done` |
| Unassigned | `assignee IS EMPTY AND status = "To Do"` |
| Recently updated | `updated >= -7d ORDER BY updated DESC` |
| Epic children | `parent = PROJ-100` |
| By label | `labels = "backend"` |

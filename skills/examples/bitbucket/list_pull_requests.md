# list_pull_requests

List pull requests in a repository with optional state filtering and field selection.

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `repo_slug` | Yes | Repository slug |
| `state` | No | Filter: `OPEN`, `MERGED`, `DECLINED`, `SUPERSEDED` |
| `fields` | No | Comma-separated fields to reduce payload |

## Field Selection

Use `fields` to minimize response size:

```
values.id,values.title,values.state,values.source.branch.name,values.destination.branch.name
```

**Common fields:**
- `values.id` - PR number
- `values.title` - PR title
- `values.state` - Current state
- `values.source.branch.name` - Source branch
- `values.destination.branch.name` - Target branch
- `values.author.display_name` - Author name

## Examples

### List open PRs with minimal fields

```bash
npx tsx .claude/skills/bitbucket-mcp/list_pull_requests.ts '{"repo_slug": "my-repo", "state": "OPEN", "fields": "values.id,values.title,values.state,values.source.branch.name"}'
```

### List all PRs (no filter)

```bash
npx tsx .claude/skills/bitbucket-mcp/list_pull_requests.ts '{"repo_slug": "my-repo", "fields": "values.id,values.title,values.state"}'
```

## Return Format

```json
{
  "values": [
    {
      "id": 123,
      "title": "Add feature X",
      "state": "OPEN",
      "source": { "branch": { "name": "feature/x" } }
    }
  ]
}
```

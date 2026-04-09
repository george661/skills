# get_pull_request

Get detailed information about a specific pull request.

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `repo_slug` | Yes | Repository slug |
| `pull_request_id` | Yes | PR number |
| `fields` | No | Comma-separated fields to reduce payload |

## Field Selection

```
id,title,state,source.branch.name,destination.branch.name,description,author.display_name
```

**Common fields:**
- `id` - PR number
- `title` - PR title
- `state` - Current state
- `description` - PR description/body
- `source.branch.name` - Source branch
- `destination.branch.name` - Target branch
- `author.display_name` - Author name
- `created_on` - Creation timestamp
- `updated_on` - Last update timestamp

## Examples

### Get PR with key details

```bash
npx tsx .claude/skills/bitbucket-mcp/get_pull_request.ts '{"repo_slug": "my-repo", "pull_request_id": 123, "fields": "id,title,state,source.branch.name,destination.branch.name,description"}'
```

### Get PR for merge decision

```bash
npx tsx .claude/skills/bitbucket-mcp/get_pull_request.ts '{"repo_slug": "my-repo", "pull_request_id": 123, "fields": "id,state,source.branch.name,destination.branch.name"}'
```

## Return Format

```json
{
  "id": 123,
  "title": "Add feature X",
  "state": "OPEN",
  "description": "This PR adds...",
  "source": { "branch": { "name": "feature/x" } },
  "destination": { "branch": { "name": "main" } }
}
```

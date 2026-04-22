# list_pull_requests

List pull requests in a repository with optional state filtering and field selection.

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `repo_slug` | Yes | Repository slug |
| `state` | No | Filter: `OPEN`, `MERGED`, `DECLINED`, `SUPERSEDED` |
| `source_branch` | No | Filter by source branch name (exact match) |
| `fields` | No | Comma-separated fields to reduce payload |

> When `source_branch` is set, `state` is folded into Bitbucket's BBQL `q`
> expression. Bitbucket's plain `state=` param is silently ignored whenever
> `q` is present, so the skill combines them into one clause.

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

### Find a MERGED PR for a specific branch (cleanup-worktrees Tier 2)

```bash
npx tsx .claude/skills/bitbucket-mcp/list_pull_requests.ts '{"repo_slug": "my-repo", "state": "MERGED", "source_branch": "FOO-123-my-branch"}'
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

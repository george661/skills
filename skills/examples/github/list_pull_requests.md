# list_pull_requests

List pull requests for a repository with optional filters.

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `owner` | Yes | Repository owner (org or user) |
| `repo` | Yes | Repository name |
| `state` | No | Filter by state: `open`, `closed`, `all` |
| `head` | No | Filter by head branch (format: `user:branch`) |
| `base` | No | Filter by base branch |
| `sort` | No | Sort by: `created`, `updated`, `popularity` |
| `direction` | No | Sort direction: `asc`, `desc` |
| `per_page` | No | Results per page (max 100) |

## Examples

### List open PRs

```bash
npx tsx .claude/skills/github-mcp/list_pull_requests.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "state": "open"}'
```

### List PRs for a specific branch

```bash
npx tsx .claude/skills/github-mcp/list_pull_requests.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "state": "open", "head": "${TENANT_WORKSPACE}:${TENANT_BRANCH_PREFIX}${TENANT_PROJECT}-123"}'
```

### List recently updated PRs

```bash
npx tsx .claude/skills/github-mcp/list_pull_requests.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "state": "all", "sort": "updated", "direction": "desc", "per_page": 10}'
```

## Return Format

```json
[
  {
    "number": 123,
    "title": "PROJ-123: Add feature",
    "state": "open",
    "head": { "ref": "agent/PROJ-123" },
    "base": { "ref": "main" },
    "user": { "login": "author" },
    "html_url": "https://github.com/owner/repo/pull/123"
  }
]
```

## Bitbucket Equivalent

`npx tsx .claude/skills/bitbucket-mcp/list_pull_requests.ts` - Note parameter differences:
- `owner` (GitHub) = `workspace` (Bitbucket)
- `repo` (GitHub) = `repo_slug` (Bitbucket)
- `state` values differ: GitHub uses lowercase, Bitbucket uses UPPERCASE

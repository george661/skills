# get_pull_request

Get details of a specific pull request by number.

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `owner` | Yes | Repository owner (org or user) |
| `repo` | Yes | Repository name |
| `pull_number` | Yes | PR number |

## Examples

### Get PR details

```bash
npx tsx .claude/skills/github-mcp/get_pull_request.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "pull_number": 123}'
```

## Return Format

```json
{
  "number": 123,
  "title": "PROJ-123: Add feature",
  "state": "open",
  "merged": false,
  "mergeable": true,
  "head": {
    "ref": "agent/PROJ-123",
    "sha": "abc123"
  },
  "base": {
    "ref": "main"
  },
  "user": {
    "login": "author"
  },
  "html_url": "https://github.com/owner/repo/pull/123",
  "created_at": "2025-01-08T10:00:00Z",
  "updated_at": "2025-01-08T12:00:00Z"
}
```

## Key Fields

| Field | Description |
|-------|-------------|
| `state` | `open`, `closed` |
| `merged` | Whether PR was merged (when state=closed) |
| `mergeable` | Can be merged without conflicts |
| `head.ref` | Source branch |
| `base.ref` | Target branch |

## Bitbucket Equivalent

`npx tsx .claude/skills/bitbucket-mcp/get_pull_request.ts` - Note parameter differences:
- `owner` (GitHub) = `workspace` (Bitbucket)
- `repo` (GitHub) = `repo_slug` (Bitbucket)
- `pull_number` (GitHub) = `pull_request_id` (Bitbucket)

## Status Mapping

| GitHub | Bitbucket | Meaning |
|--------|-----------|---------|
| `open` | `OPEN` | PR is open |
| `closed` (merged=true) | `MERGED` | PR was merged |
| `closed` (merged=false) | `DECLINED` | PR closed without merge |

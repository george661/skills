# merge_pull_request

Merge a pull request.

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `owner` | Yes | Repository owner (org or user) |
| `repo` | Yes | Repository name |
| `pull_number` | Yes | PR number |
| `commit_title` | No | Custom merge commit title |
| `commit_message` | No | Custom merge commit message |
| `merge_method` | No | Merge strategy: `merge`, `squash`, `rebase` |

## Merge Methods

| Method | Description |
|--------|-------------|
| `merge` | Create merge commit (default) |
| `squash` | Squash all commits into one |
| `rebase` | Rebase commits onto base |

## Examples

### Basic merge

```bash
npx tsx .claude/skills/github-mcp/merge_pull_request.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "pull_number": 123}'
```

### Squash merge with custom message

```bash
npx tsx .claude/skills/github-mcp/merge_pull_request.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "pull_number": 123, "merge_method": "squash", "commit_title": "${TENANT_PROJECT}-123: Add user authentication", "commit_message": "Implements OAuth2 login flow with session management."}'
```

### Rebase merge

```bash
npx tsx .claude/skills/github-mcp/merge_pull_request.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "pull_number": 123, "merge_method": "rebase"}'
```

## Return Format

```json
{
  "sha": "abc123def456",
  "merged": true,
  "message": "Pull Request successfully merged"
}
```

## Bitbucket Equivalent

`npx tsx .claude/skills/bitbucket-mcp/merge_pull_request.ts` - Note parameter differences:
- `owner` (GitHub) = `workspace` (Bitbucket)
- `repo` (GitHub) = `repo_slug` (Bitbucket)
- `pull_number` (GitHub) = `pull_request_id` (Bitbucket)
- `merge_method` (GitHub) = `strategy` (Bitbucket)

### Merge Strategy Mapping

| GitHub | Bitbucket |
|--------|-----------|
| `merge` | `merge-commit` |
| `squash` | `squash` |
| `rebase` | `fast-forward` |

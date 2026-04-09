# create_pull_request

Create a new pull request from a feature branch.

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `owner` | Yes | Repository owner (org or user) |
| `repo` | Yes | Repository name |
| `title` | Yes | PR title |
| `head` | Yes | Source branch name |
| `base` | Yes | Target branch name |
| `body` | No | PR description in markdown |
| `draft` | No | Create as draft PR |

## Description Template

Use markdown for structured descriptions:

```markdown
## Summary
Brief description of changes.

## Changes
- Change 1
- Change 2

## Testing
How this was tested.

## Related Issues
Closes #123
```

## Examples

### Basic PR creation

```bash
npx tsx .claude/skills/github-mcp/create_pull_request.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "title": "${TENANT_PROJECT}-123: Add user authentication", "head": "${TENANT_BRANCH_PREFIX}${TENANT_PROJECT}-123", "base": "${TENANT_BASE_BRANCH}"}'
```

### PR with full details

```bash
npx tsx .claude/skills/github-mcp/create_pull_request.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "title": "${TENANT_PROJECT}-456: Update API endpoints", "head": "${TENANT_BRANCH_PREFIX}${TENANT_PROJECT}-456", "base": "develop", "body": "## Summary\nUpdates REST API endpoints.\n\n## Testing\nUnit tests added.\n\nCloses #456", "draft": false}'
```

## Return Format

Returns the created PR object with `number`, `title`, `state`, `html_url`, and links.

## Bitbucket Equivalent

`npx tsx .claude/skills/bitbucket-mcp/create_pull_request.ts` - Note parameter differences:
- `owner` (GitHub) = `workspace` (Bitbucket)
- `repo` (GitHub) = `repo_slug` (Bitbucket)
- `head` (GitHub) = `sourceBranch` (Bitbucket)
- `base` (GitHub) = `targetBranch` (Bitbucket)
- `body` (GitHub) = `description` (Bitbucket)

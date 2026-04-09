# create_pull_request

Create a new pull request from a feature branch.

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `repo_slug` | Yes | Repository slug |
| `title` | Yes | PR title |
| `source_branch` | Yes | Source branch name |
| `target_branch` | No | Target branch (defaults to configured default) |
| `description` | No | PR description in markdown |
| `reviewers` | No | Array of reviewer usernames |
| `close_source_branch` | No | Delete source branch after merge |

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
JIRA-123
```

## Examples

### Basic PR creation

```bash
npx tsx .claude/skills/bitbucket-mcp/create_pull_request.ts '{"repo_slug": "my-repo", "title": "JIRA-123: Add user authentication", "source_branch": "feature/JIRA-123-auth", "close_source_branch": true}'
```

### PR with full details

```bash
npx tsx .claude/skills/bitbucket-mcp/create_pull_request.ts '{"repo_slug": "my-repo", "title": "JIRA-456: Update API endpoints", "source_branch": "feature/JIRA-456-api", "target_branch": "develop", "description": "## Summary\nUpdates REST API endpoints.\n\n## Testing\nUnit tests added.", "reviewers": ["john.doe", "jane.smith"], "close_source_branch": true}'
```

## Return Format

Returns the created PR object with `id`, `title`, `state`, and links.

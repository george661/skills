# merge_pull_request

Merge a pull request. Use after pipeline passes and reviews are complete.

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `repo_slug` | Yes | Repository slug |
| `pull_request_id` | Yes | PR number |
| `message` | No | Merge commit message |
| `strategy` | No | Merge strategy |
| `close_source_branch` | No | Delete source branch after merge |

## Merge Strategies

| Strategy | Description | Use When |
|----------|-------------|----------|
| `merge_commit` | Creates merge commit | Default, preserves full history |
| `squash` | Squashes all commits into one | Clean history, many small commits |
| `fast_forward` | No merge commit | Linear history, branch is ahead |

## Examples

### Standard merge with commit

```bash
npx tsx .claude/skills/bitbucket-mcp/merge_pull_request.ts '{"repo_slug": "my-repo", "pull_request_id": 123, "message": "Merge PR #123: Add user authentication", "strategy": "merge_commit", "close_source_branch": true}'
```

### Squash merge for clean history

```bash
npx tsx .claude/skills/bitbucket-mcp/merge_pull_request.ts '{"repo_slug": "my-repo", "pull_request_id": 123, "message": "JIRA-456: Implement feature X", "strategy": "squash", "close_source_branch": true}'
```

### Fast-forward merge

```bash
npx tsx .claude/skills/bitbucket-mcp/merge_pull_request.ts '{"repo_slug": "my-repo", "pull_request_id": 123, "strategy": "fast_forward", "close_source_branch": true}'
```

## Pre-Merge Checklist

1. Pipeline passed (check `list_pipelines`)
2. Reviews approved
3. No merge conflicts
4. Branch is up to date with target

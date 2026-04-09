# create_pr_comment

Add a comment to a pull request. Supports general comments and review comments on specific lines.

## Parameters

### General Comment (Issue Comment)

| Parameter | Required | Description |
|-----------|----------|-------------|
| `owner` | Yes | Repository owner (org or user) |
| `repo` | Yes | Repository name |
| `issue_number` | Yes | PR number (PRs are issues in GitHub API) |
| `body` | Yes | Comment content in markdown |

### Review Comment (Inline)

| Parameter | Required | Description |
|-----------|----------|-------------|
| `owner` | Yes | Repository owner (org or user) |
| `repo` | Yes | Repository name |
| `pull_number` | Yes | PR number |
| `body` | Yes | Comment content in markdown |
| `path` | Yes | File path for inline comment |
| `line` | Yes | Line number for inline comment |
| `commit_id` | Yes | SHA of the commit to comment on |

## Comment Types

### General Comment
Appears in PR conversation. Use for overall feedback.

### Review Comment (Inline)
Attached to specific code line. Requires `path`, `line`, and `commit_id`.

## Examples

### General PR comment

```bash
npx tsx .claude/skills/github-mcp/create_issue_comment.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "issue_number": 123, "body": "LGTM! Approved after reviewing the changes."}'
```

### Request changes comment

```bash
npx tsx .claude/skills/github-mcp/create_issue_comment.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "issue_number": 123, "body": "## Changes Requested\n\n- Add error handling for edge case\n- Update unit tests"}'
```

### Inline code comment (Review Comment)

```bash
npx tsx .claude/skills/github-mcp/create_pull_request_review_comment.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "pull_number": 123, "body": "Consider using `const` here instead of `let` since the value is never reassigned.", "path": "src/utils/helper.js", "line": 42, "commit_id": "abc123def456"}'
```

### Inline comment with suggestion

```bash
npx tsx .claude/skills/github-mcp/create_pull_request_review_comment.ts '{"owner": "${TENANT_WORKSPACE}", "repo": "my-repo", "pull_number": 123, "body": "This could be simplified:\n```suggestion\nreturn items.filter(Boolean);\n```", "path": "src/api/handler.ts", "line": 15, "commit_id": "abc123def456"}'
```

## Markdown Support

Comments support full markdown:
- Code blocks with syntax highlighting
- `suggestion` blocks for inline suggestions
- Lists and headers
- Links and mentions (`@username`)

## Bitbucket Equivalent

`npx tsx .claude/skills/bitbucket-mcp/add_pull_request_comment.ts` - Note differences:
- GitHub separates general comments (issue_comment) and review comments
- Bitbucket uses single endpoint for both
- GitHub requires `commit_id` for review comments
- `issue_number` (GitHub general) = `pull_request_id` (Bitbucket)

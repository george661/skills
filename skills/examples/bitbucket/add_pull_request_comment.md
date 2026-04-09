# add_pull_request_comment

Add a comment to a pull request. Supports general comments and inline code comments.

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `repo_slug` | Yes | Repository slug |
| `pull_request_id` | Yes | PR number |
| `content` | Yes | Comment content in markdown |
| `path` | No | File path for inline comment |
| `line` | No | Line number for inline comment |

## Comment Types

### General Comment
Appears in PR conversation. Use for overall feedback.

### Inline Comment
Attached to specific code line. Requires `path` and `line`.

## Examples

### General PR comment

```bash
npx tsx .claude/skills/bitbucket-mcp/add_pull_request_comment.ts '{"repo_slug": "my-repo", "pull_request_id": 123, "content": "LGTM! Approved after reviewing the changes."}'
```

### Request changes comment

```bash
npx tsx .claude/skills/bitbucket-mcp/add_pull_request_comment.ts '{"repo_slug": "my-repo", "pull_request_id": 123, "content": "## Changes Requested\n\n- Add error handling for edge case\n- Update unit tests"}'
```

### Inline code comment

```bash
npx tsx .claude/skills/bitbucket-mcp/add_pull_request_comment.ts '{"repo_slug": "my-repo", "pull_request_id": 123, "content": "Consider using `const` here instead of `let` since the value is never reassigned.", "path": "src/utils/helper.js", "line": 42}'
```

### Inline comment with suggestion

```bash
npx tsx .claude/skills/bitbucket-mcp/add_pull_request_comment.ts '{"repo_slug": "my-repo", "pull_request_id": 123, "content": "This could be simplified:\n```javascript\nreturn items.filter(Boolean);\n```", "path": "src/api/handler.ts", "line": 15}'
```

## Markdown Support

Comments support full markdown:
- Code blocks with syntax highlighting
- Lists and headers
- Links and mentions (`@username`)

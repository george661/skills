# add_comment

Add a comment to an issue. Supports Jira markdown formatting.

## Parameters

- `issue_key` - Issue identifier (required)
- `body` - Comment text with Jira markdown (required)

## Examples

### Simple comment
```bash
npx tsx .claude/skills/jira-mcp/add_comment.ts '{"issue_key": "PROJ-123", "body": "Completed initial implementation. Ready for review."}'
```

### Comment with formatting
```bash
npx tsx .claude/skills/jira-mcp/add_comment.ts '{"issue_key": "PROJ-123", "body": "## Implementation Notes\n\n*Files changed:*\n- `src/auth/jwt.ts` - Added validation\n- `src/middleware/auth.ts` - New middleware\n\n{code:javascript}\nconst token = await validateJWT(req.headers.authorization);\n{code}\n\n[PR Link|https://bitbucket.org/team/repo/pull-requests/45]"}'
```

### Bug investigation update
```bash
npx tsx .claude/skills/jira-mcp/add_comment.ts '{"issue_key": "PROJ-456", "body": "## Root Cause\n\nSpecial characters not being URL-encoded before API call.\n\n## Fix\n\nAdded `encodeURIComponent()` wrapper in `auth.service.ts:42`\n\n## Testing\n\n- [x] Unit tests added\n- [x] Manual testing passed\n- [ ] Staging deployment pending"}'
```

## Jira Markdown Reference

| Format | Syntax |
|--------|--------|
| Bold | `*bold text*` |
| Italic | `_italic text_` |
| Code inline | `{{code}}` |
| Code block | `{code:lang}...{code}` |
| Link | `[text\|url]` |
| Heading | `h2. Heading` or `## Heading` |
| Bullet list | `* item` or `- item` |
| Numbered | `# item` |
| Mention | `[~accountId]` |

## Return Format

```json
{
  "id": "10045",
  "body": "Comment text...",
  "created": "2024-01-15T10:30:00.000+0000",
  "author": {
    "displayName": "User Name"
  }
}
```

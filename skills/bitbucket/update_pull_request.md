---
name: bitbucket:update_pull_request
description: Update a pull request title or description.
---

# update_pull_request

Update the title or description of a pull request in a Bitbucket repository.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo_slug` | string | Yes | The repository slug (URL-friendly name) |
| `pull_request_id` | number | Yes | The pull request ID number |
| `title` | string | No | New title |
| `description` | string | No | New description in markdown |

## Example

```typescript
// Update title only
npx tsx ~/.claude/skills/bitbucket/update_pull_request.ts '{"repo_slug": "my-repo", "pull_request_id": 15, "title": "PROJ-123: Add user authentication (updated)"}'

// Update description
npx tsx ~/.claude/skills/bitbucket/update_pull_request.ts '{"repo_slug": "my-repo", "pull_request_id": 15, "description": "## Summary\n- Added login functionality\n- Added logout functionality\n\n## Changes\n- Updated based on review feedback"}'

// Update both
npx tsx ~/.claude/skills/bitbucket/update_pull_request.ts '{"repo_slug": "my-repo", "pull_request_id": 15, "title": "New Title", "description": "New description"}'
```

## Notes

- Only provide the fields you want to update; others remain unchanged
- The description supports markdown formatting
- Useful for updating PR details after addressing review comments

---
name: bitbucket:create_branch
description: Create a new branch from a specific commit. Typically used to create feature branches from main.
---

# create_branch

Create a new branch in a Bitbucket repository. This is typically used to create feature branches from the main branch before starting work on a new feature or bug fix.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo_slug` | string | Yes | The repository slug (URL-friendly name) |
| `branch_name` | string | Yes | Name for the new branch (e.g., "feature/issue-123-add-login") |
| `from_branch` | string | No | Source branch to create from (defaults to configured default branch) |
| `target_commit` | string | No | Specific commit hash to branch from (optional, uses latest from from_branch) |

## Example

```typescript
// Create branch from default branch
npx tsx ~/.claude/skills/bitbucket/create_branch.ts '{"repo_slug": "my-repo", "branch_name": "feature/PROJ-123-new-feature"}'

// Create branch from specific branch
npx tsx ~/.claude/skills/bitbucket/create_branch.ts '{"repo_slug": "my-repo", "branch_name": "feature/PROJ-123-new-feature", "from_branch": "develop"}'

// Create branch from specific commit
npx tsx ~/.claude/skills/bitbucket/create_branch.ts '{"repo_slug": "my-repo", "branch_name": "hotfix/urgent-fix", "target_commit": "abc123def456"}'
```

## Notes

- Branch names should follow your team's naming convention (e.g., `feature/`, `bugfix/`, `hotfix/`)
- If neither `from_branch` nor `target_commit` is specified, the branch is created from the default branch
- The branch name should be URL-friendly (no spaces)

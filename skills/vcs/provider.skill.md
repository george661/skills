---
name: vcs-provider
description: VCS provider abstraction - unified interface that auto-routes to Bitbucket or GitHub
---

# VCS Provider Abstraction

Unified VCS skills in `~/.claude/skills/vcs/` that auto-detect the provider and delegate to `bitbucket/` or `github-mcp/` backends. **Commands should ONLY call `vcs/*` skills — never call provider-specific skills directly.**

## How It Works

```
vcs/get_pull_request.ts  ──►  vcs-router.ts  ──►  bitbucket/get_pull_request.ts
                                    │                    OR
                                    └──────►  github-mcp/get_pull_request.ts
```

The router resolves the provider via:
1. Explicit `provider` field in input
2. `~/.claude/config/repo-vcs.json` lookup by repo name
3. Git remote URL detection at `$WORKSPACE_ROOT/<repo>/`
4. Default: bitbucket

## Unified Interface

All VCS skills use **provider-agnostic parameter names**. The router translates automatically:

| Unified Param | Bitbucket | GitHub |
|--------------|-----------|--------|
| `repo` | `repo_slug` | `repo` (+ `owner` injected) |
| `pr_number` | `pull_request_id` | `pull_number` |
| `comment_text` | `content` | `body` |
| `source_branch` | `source_branch` | `head` |
| `target_branch` | `target_branch` | `base` |
| `description` | `description` | `body` (on create_pull_request) |
| `state: "open"` | auto-uppercased to `OPEN` | kept as `open` |

## Available VCS Skills

### Pull Request Operations

```bash
# All examples use the SAME unified interface regardless of provider

# Get PR details
npx tsx ~/.claude/skills/vcs/get_pull_request.ts '{"repo": "my-repo", "pr_number": 42}'

# Create PR
npx tsx ~/.claude/skills/vcs/create_pull_request.ts '{"repo": "my-repo", "title": "PROJ-123: Add feature", "source_branch": "agent/PROJ-123", "description": "..."}'

# List PRs
npx tsx ~/.claude/skills/vcs/list_pull_requests.ts '{"repo": "my-repo", "state": "open"}'

# Merge PR
npx tsx ~/.claude/skills/vcs/merge_pull_request.ts '{"repo": "my-repo", "pr_number": 42}'

# Get PR diff
npx tsx ~/.claude/skills/vcs/get_pull_request_diff.ts '{"repo": "my-repo", "pr_number": 42}'

# Add comment (general or inline)
npx tsx ~/.claude/skills/vcs/add_pull_request_comment.ts '{"repo": "my-repo", "pr_number": 42, "comment_text": "LGTM"}'
npx tsx ~/.claude/skills/vcs/add_pull_request_comment.ts '{"repo": "my-repo", "pr_number": 42, "comment_text": "Fix this", "path": "src/index.ts", "line": 15}'

# List comments
npx tsx ~/.claude/skills/vcs/list_pull_request_comments.ts '{"repo": "my-repo", "pr_number": 42}'
```

### CI Operations

CI is also unified — routes to Concourse (fly) or GitHub Actions automatically:

```bash
# Wait for CI to complete
npx tsx ~/.claude/skills/vcs/wait_for_ci.ts '{"repo": "my-repo", "branch": "agent/PROJ-123", "timeout_seconds": 600}'

# Get CI logs (for debugging failures)
npx tsx ~/.claude/skills/vcs/get_ci_logs.ts '{"repo": "my-repo", "run_id": 12345}'
```

## Provider Configuration

### Per-Repo Config (`~/.claude/config/repo-vcs.json`)

```json
{
  "my-repo": {
    "provider": "github",
    "owner": "your-org",
    "remote_repo": "my-sdk",
    "ci": "github-actions"
  }
}
```

Only repos that differ from the default (bitbucket) need entries. The router auto-detects from git remotes for unconfigured repos.

## Backend Skills

| Provider | Directory | Auth |
|----------|-----------|------|
| Bitbucket | `~/.claude/skills/bitbucket/` | Basic auth via env/settings |
| GitHub | `~/.claude/skills/github-mcp/` | `gh` CLI keyring |

## PR State Mapping

| Bitbucket | GitHub | Meaning |
|-----------|--------|---------|
| `OPEN` | `open` | PR is open |
| `MERGED` | `closed` (merged=true) | PR was merged |
| `DECLINED` | `closed` (merged=false) | PR closed without merge |

## Branch Naming

Both providers use the same convention: `${TENANT_BRANCH_PREFIX}${TENANT_PROJECT}-{issue_number}` (e.g., `agent/PROJ-123`)

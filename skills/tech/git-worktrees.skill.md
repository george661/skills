---
name: git-worktrees
description: Use when working on multiple issues in parallel, isolating work per branch, or needing to context-switch without stashing - covers worktree creation, branch management, cleanup, and multi-issue workflows
---

# Git Worktrees

## Quick Reference

| Command | Purpose |
|---------|---------|
| `git worktree add <path> <branch>` | Create worktree for existing branch |
| `git worktree add -b <branch> <path>` | Create worktree with new branch |
| `git worktree list` | List all worktrees |
| `git worktree remove <path>` | Remove worktree (keeps branch) |
| `git worktree prune` | Clean stale worktree references |

## Directory Convention

```
project/
├── main/              # Primary checkout (main branch)
├── worktrees/
│   ├── PROJ-123/      # Feature branch worktree
│   ├── PROJ-456/      # Another feature worktree
│   └── hotfix-auth/   # Hotfix worktree
```

## Creating Worktrees

### New Feature Branch

```bash
git fetch origin
git worktree add -b feature/PROJ-123 ../worktrees/PROJ-123 origin/main
cd ../worktrees/PROJ-123
git push -u origin feature/PROJ-123   # Set upstream tracking
```

### Existing Branch

```bash
git fetch origin
git worktree add ../worktrees/PROJ-456 origin/feature/PROJ-456
```

## Multi-Issue Workflow

### Parallel Development

```bash
# Issue 1: Start work
git worktree add -b feature/PROJ-100 ../worktrees/PROJ-100 origin/main
cd ../worktrees/PROJ-100
# ... implement, commit, push, create PR

# Issue 2: Start while PR pending
cd ../main
git worktree add -b feature/PROJ-101 ../worktrees/PROJ-101 origin/main
cd ../worktrees/PROJ-101
# ... implement in parallel

# Switch context instantly - no stash needed
cd ../worktrees/PROJ-100
```

### After PR Merged

```bash
cd ../main
git fetch origin
git worktree remove ../worktrees/PROJ-100
git branch -d feature/PROJ-100
```

## Cleanup

### Remove Worktree

```bash
git worktree remove ../worktrees/PROJ-123          # Graceful (fails if uncommitted)
git worktree remove --force ../worktrees/PROJ-123  # Force (discards changes)
```

### Full Cleanup Sequence

```bash
git worktree list                           # Review active worktrees
git worktree remove ../worktrees/PROJ-123   # Remove worktree
git branch -d feature/PROJ-123              # Delete local branch
git push origin --delete feature/PROJ-123   # Delete remote branch
git worktree prune                          # Clean stale references
```

## Common Patterns

### Dependencies Per Worktree

```bash
cd ../worktrees/PROJ-123
npm ci    # Each worktree needs own node_modules
```

### Shared Git Config

Worktrees share `.git` metadata with main checkout (remotes, hooks, config) but have independent working directory, index, and HEAD.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "branch already checked out" | Remove existing worktree first |
| "not a valid worktree" | Run `git worktree prune` |
| Stale after manual deletion | Run `git worktree prune` |
| Need to rename worktree | Remove and recreate |

## Workflow Integration

The `/create-implementation-plan` command creates worktrees automatically:

```bash
# Worktree: ../worktrees/{issue-key}
# Branch: feature/{issue-key}
# Tracked in AgentDB: worktree-{issue-key}
```

Always work in the worktree for the active issue, not the main checkout.

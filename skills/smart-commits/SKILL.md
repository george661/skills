---
name: Smart Commits
description: Atlassian Smart Commits syntax for managing Jira issues directly from git commit messages. Supports transitions, comments, and time logging.
---

# Smart Commits Skill

## Purpose

Smart Commits allow you to manage Jira issues directly from git commit messages. When commits are pushed to Bitbucket (or GitHub with Jira integration), Jira automatically processes the embedded commands.

**Reference**: [Atlassian Smart Commits Documentation](https://support.atlassian.com/bitbucket-cloud/docs/use-smart-commits/)

## Basic Syntax

```
<ignored text> <ISSUE_KEY> <ignored text> #<COMMAND> <optional COMMAND_ARGUMENTS>
```

- **ISSUE_KEY**: Jira issue key in format `PROJECT-123` (uppercase letters + hyphen + number)
- **COMMAND**: One of `comment`, `time`, or a transition name
- Any text between the issue key and command is ignored

## Commands

### 1. Comment (`#comment`)

Add a comment to a Jira issue.

**Syntax**:
```
<ISSUE_KEY> #comment <comment_string>
```

**Examples**:
```bash
# Single issue comment
git commit -m "PROJ-123 #comment Fixed the null pointer exception in auth flow"

# Comment with context
git commit -m "Refactoring auth module PROJ-123 #comment Extracted validation logic to separate function"
```

### 2. Time Logging (`#time`)

Record time spent on an issue. Time tracking must be enabled in Jira.

**Syntax**:
```
<ISSUE_KEY> #time <value>w <value>d <value>h <value>m <optional_comment>
```

| Unit | Meaning |
|------|---------|
| `w` | Weeks |
| `d` | Days |
| `h` | Hours |
| `m` | Minutes |

**Examples**:
```bash
# Log 2 hours 30 minutes
git commit -m "PROJ-123 #time 2h 30m Implemented user validation"

# Log 1 day 4 hours with comment
git commit -m "PROJ-456 #time 1d 4h Completed API integration and testing"

# Decimal values allowed
git commit -m "PROJ-789 #time 1.5h Quick bugfix"
```

### 3. Transitions (`#<transition_name>`)

Move issues through workflow states. Use the transition name from your Jira workflow.

**Syntax**:
```
<ISSUE_KEY> #<transition_name> #comment <optional_comment>
```

**Common Transitions**:

| Transition | Command |
|------------|---------|
| Start Progress | `#start-progress` |
| In Review | `#in-review` |
| Resolve | `#resolve` |
| Close | `#close` |
| Reopen | `#reopen` |

**Examples**:
```bash
# Close an issue
git commit -m "PROJ-123 #close #comment Verified fix in staging"

# Resolve with comment
git commit -m "PROJ-456 #resolve #comment All tests passing"

# Start work on issue
git commit -m "PROJ-789 #start-progress Beginning implementation"
```

**Transition Name Rules**:
- Only text before first space is processed: `#finish` works for "Finish Work"
- Use hyphens for multi-word transitions: `#start-progress`, `#in-review`
- Cannot set Resolution field via Smart Commits

## Advanced Usage

### Multiple Commands on One Issue

Combine commands in a single commit:

```bash
# Log time, comment, and resolve
git commit -m "PROJ-123 #time 2h 30m #comment Completed implementation #resolve"

# Start work and add comment
git commit -m "PROJ-456 #start-progress #comment Beginning frontend work"
```

### Single Command on Multiple Issues

Apply one command to multiple issues:

```bash
# Resolve multiple related issues
git commit -m "PROJ-123 PROJ-124 PROJ-125 #resolve #comment Fixed in shared auth module"

# Comment on multiple issues
git commit -m "PROJ-100 PROJ-101 #comment Updated in refactoring PR"
```

### Multiple Commands on Multiple Issues

All commands apply to all listed issues:

```bash
# Close and comment on multiple issues
git commit -m "PROJ-200 PROJ-201 PROJ-202 #time 1h #comment Batch fix #close"
```

## Integration with Branch Naming

Combine Smart Commits with branch naming conventions:

```bash
# Branch name follows convention: {ISSUE_KEY}-{description}
git checkout -b PROJ-123-add-user-authentication

# Commits automatically reference the issue
git commit -m "PROJ-123 #comment Added JWT validation middleware"
git commit -m "PROJ-123 #time 3h Implemented auth flow #resolve"
```

## Commit Message Templates

### Feature Implementation

```bash
git commit -m "$(cat <<'EOF'
PROJ-123 #time 4h Implement user authentication

- Added JWT token validation
- Created auth middleware
- Added unit tests

#comment Implementation complete, ready for review

Generated with [Claude Code](https://claude.ai/code)
via [Happy](https://happy.engineering)

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Happy <yesreply@happy.engineering>
EOF
)"
```

### Bug Fix

```bash
git commit -m "$(cat <<'EOF'
PROJ-456 #time 1h 30m Fix null pointer in session handler

Root cause: Missing null check on user context
Fix: Added defensive null check and early return

#comment Fixed and verified in dev environment #resolve

Generated with [Claude Code](https://claude.ai/code)
via [Happy](https://happy.engineering)

Co-Authored-By: Claude <noreply@anthropic.com>
Co-Authored-By: Happy <yesreply@happy.engineering>
EOF
)"
```

### Quick Fix

```bash
git commit -m "PROJ-789 #time 15m #comment Fixed typo in error message #resolve"
```

## Requirements

1. **Email Matching**: Committer's email must exactly match a Jira user account
2. **Permissions**: User must have appropriate permissions:
   - Commenting permission for `#comment`
   - Work logging permission for `#time`
   - Transition permission for workflow commands
3. **Time Tracking**: Must be enabled by Jira admin for `#time` command
4. **Integration**: Bitbucket/GitHub must be linked to Jira

## Limitations

| Limitation | Details |
|------------|---------|
| Single line only | Commands cannot span multiple lines |
| Key format | Only default format: `PROJECT-123` |
| Email strict | Exact match required; mismatches fail silently |
| No Resolution | Cannot set Resolution field via Smart Commits |
| Each line needs key | In multiline commits, each line needs its own issue key |

## Troubleshooting

### Commands Not Processing

1. **Check email**: Verify git email matches Jira user exactly
   ```bash
   git config user.email
   ```

2. **Check permissions**: Ensure Jira user has required permissions

3. **Check integration**: Verify Bitbucket/GitHub is linked to Jira

4. **Check syntax**: Ensure issue key is uppercase and follows `PROJECT-123` format

### Time Not Logging

1. Verify time tracking is enabled in Jira
2. Check user has work logging permission
3. Ensure time format is correct: `1w 2d 3h 4m`

### Transitions Not Working

1. Verify transition name exists in workflow
2. Use first word only or hyphenated form
3. Check user has permission to execute transition
4. Ensure issue is in a state where transition is available

## See Also

- [Atlassian Smart Commits Documentation](https://support.atlassian.com/bitbucket-cloud/docs/use-smart-commits/)
- `.claude/skills/jira/` - Jira REST API skills
- `.claude/skills/bitbucket/` - Bitbucket REST API skills

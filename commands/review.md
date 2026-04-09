<!-- MODEL_TIER: opus -->
<!-- No dispatch needed - this command executes directly on the session model. -->

<!-- Integration: ISSUE_TRACKER=jira, VCS_PROVIDER=bitbucket|github -->
<!-- Future: Add conditionals when supporting other providers -->
---
description: Perform a thorough code review on a PR (Bitbucket or GitHub), leaving inline comments and Jira summary
arguments:
  - name: pr_url
    description: "PR URL (Bitbucket or GitHub) OR repo_slug and PR number (e.g., ${TENANT_REPO} 163)"
    required: true
  - name: --team
    description: Run as agent team with parallel quality, security, and test analysis
    required: false
---

<!-- Agent Team: .claude/teams/review.yaml -->
<!-- Agents: reviewer, architect, validator -->
<!-- Usage: /review api-service 42 --team -->

## Agent Team Mode

**If `--team` flag is present**, load team definition from `.claude/teams/review.yaml` and create an agent team:

```
Create an agent team using the review-team definition from .claude/teams/review.yaml.

Team composition:
- quality-analyst (reviewer agent): Code quality and requirements coverage
- security-analyst (architect agent): OWASP Top 10 and security review
- test-analyst (reviewer agent): Test coverage and adequacy
- validation-runner (validator agent): Execute local test suite

Coordinate per the lead_instructions in the team definition.
Use delegate mode during parallel analysis phase.
The PR to review is: $ARGUMENTS.pr_url
```

**If `--team` flag is NOT present**, continue with single-session execution below.

---

# Code Review: $ARGUMENTS.pr_url

## Purpose

This command performs a comprehensive code review on a PR (Bitbucket or GitHub):
> VCS abstraction: See `.claude/skills/vcs/provider.skill.md` for conditional VCS patterns
- Analyzes code quality, security, and best practices
- Verifies implementation matches Jira requirements
- Checks test coverage adequacy
- Leaves inline comments on specific issues
- Posts summary comments on PR and related Jira issue

---

## Phase 0.5: Branch Sync (MANDATORY — run before fetching diff)

Sync the feature branch with main so the review reflects the actual merge state:

```bash
cd <worktree-path>
git fetch origin main

# Count commits behind
behind=$(git rev-list --count HEAD..origin/main)
if [ "$behind" -gt 0 ]; then
  echo "[branch-sync] Branch is $behind commit(s) behind main — merging"
  git merge origin/main --no-edit
  if [ $? -ne 0 ]; then
    echo "[branch-sync] CONFLICT — resolve conflicts, commit, and re-run /review"
    exit 1
  fi
  git push
  echo "[branch-sync] Merged $behind commit(s) from main and pushed"
else
  echo "[branch-sync] Branch is up to date with main"
fi
```

---

## Command Phases

As you complete each phase, print a brief progress line (e.g. `[phase 2/N] Running validation...`).

1. Parse input and extract repo/PR info
2. Fetch PR details and diff
3. Find and load related Jira issue
4. Run local validation checks
5. Analyze code quality and security
6. Verify requirements coverage
7. Check test adequacy
8. Post inline comments on PR
9. Post summary comment on PR
10. Post summary comment on Jira

---

## Skill Reference (MANDATORY — use these exact calls)

**DO NOT use MCP tools (mcp__bitbucket__*, mcp__jira__*). Use the Bash skill calls below instead.**

### IMPORTANT: Always run skills from the platform root directory
```bash
cd $PROJECT_ROOT && npx tsx ~/.claude/skills/...
```
Running from inside a worktree's Go module directory will cause `ERR_MODULE_NOT_FOUND`.

### VCS Skills (auto-routes to Bitbucket or GitHub)

```bash
# Get PR details
npx tsx ~/.claude/skills/vcs/get_pull_request.ts '{"repo": "<repo>", "pr_number": <num>}'

# Get PR diff (returns plain text)
npx tsx ~/.claude/skills/vcs/get_pull_request_diff.ts '{"repo": "<repo>", "pr_number": <num>}'

# Add general comment to PR
npx tsx ~/.claude/skills/vcs/add_pull_request_comment.ts '{"repo": "<repo>", "pr_number": <num>, "comment_text": "<markdown>"}'

# Add inline comment on specific file/line
npx tsx ~/.claude/skills/vcs/add_pull_request_comment.ts '{"repo": "<repo>", "pr_number": <num>, "comment_text": "<text>", "path": "<file>", "line": <num>}'

# List existing PR comments
npx tsx ~/.claude/skills/vcs/list_pull_request_comments.ts '{"repo": "<repo>", "pr_number": <num>}'
```

### Jira Skills

```bash
# Get issue (note: parameter is issue_key, NOT issueKey)
npx tsx ~/.claude/skills/issues/get_issue.ts '{"issue_key": "<KEY>", "fields": "summary,status,labels"}'

# Add comment to issue
npx tsx ~/.claude/skills/issues/add_comment.ts '{"issue_key": "<KEY>", "body": "<markdown>"}'
```

### JSON Escaping
When posting comments with code blocks, use a heredoc pattern or write to a temp file to avoid shell escaping issues with backticks and special characters.

---

```bash
# Extract issue key from PR context if available; fall back to pr_url argument
npx tsx ~/.claude/skills/jira/worklog_identity.ts "{\"issue_key\": \"$ARGUMENTS.pr_url\", \"phase\": \"starting\", \"command\": \"/review\", \"message\": \"Beginning code review\"}" 2>/dev/null || true
```

---

## CGC Relationship Verification (if CGC available)

Before approving, verify the PR did not break existing relationships:

1. For each new export: `mcp__CodeGraphContext__find_code` to verify it is consumed somewhere
2. For each deleted export: `mcp__CodeGraphContext__analyze_code_relationships` to verify no remaining consumers
3. For new route/endpoint registrations: verify they connect to existing navigation/API gateway
4. If CGC unavailable: skip this check, note in review comment

If orphaned exports or broken consumers found: REQUIRES REWORK with specific file references.

---

**START NOW: Begin Phase 0/Step 0.**

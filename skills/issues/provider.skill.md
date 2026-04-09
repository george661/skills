# Unified Issue Tracker Skills

Unified interface for issue tracking across Jira, GitHub Issues, and Linear. Each skill resolves the provider, translates parameters to provider-native format, and delegates to the corresponding backend skill.

## Provider Resolution

Resolution order (first match wins):

1. Explicit `provider` parameter on the call
2. `ISSUE_TRACKER` environment variable
3. Default: `jira`

### Environment Variable

```bash
export ISSUE_TRACKER=jira      # Atlassian Jira (default)
export ISSUE_TRACKER=github    # GitHub Issues
export ISSUE_TRACKER=linear    # Linear
```

## Issue Key Format by Provider

| Provider | `issue_key` format | `project_key` format |
|----------|-------------------|---------------------|
| Jira     | `PROJ-123`        | `PROJ`              |
| GitHub   | `owner/repo#123`  | `owner/repo`        |
| Linear   | `TEAM-123`        | `TEAM`              |

## Skills

| Skill | Description | Required Params | Optional Params |
|-------|-------------|-----------------|-----------------|
| `get_issue` | Fetch a single issue | `issue_key` | `fields`, `provider` |
| `search_issues` | Search/query issues | `jql` | `max_results`, `fields`, `provider` |
| `create_issue` | Create a new issue | `project_key`, `summary` | `issue_type`, `description`, `labels`, `priority`, `provider` |
| `update_issue` | Update issue fields | `issue_key` | `summary`, `description`, `labels`, `priority`, `provider` |
| `transition_issue` | Change issue state | `issue_key` | `transition_id`, `state`, `provider` |
| `add_comment` | Add a comment | `issue_key`, `body` | `provider` |
| `list_comments` | List all comments | `issue_key` | `provider` |
| `list_transitions` | List available transitions/states | `issue_key` | `provider` |
| `add_worklog` | Log time spent | `issue_key`, `time_spent` | `comment`, `provider` |
| `assign_issue` | Assign issue to a user | `issue_key`, `assignee` | `provider` |

## Example Invocations

### Jira (default)

```bash
npx tsx skills/issues/get_issue.ts '{"issue_key": "PROJ-123"}'
npx tsx skills/issues/search_issues.ts '{"jql": "project = PROJ AND status = \"To Do\"", "max_results": 10}'
npx tsx skills/issues/create_issue.ts '{"project_key": "PROJ", "summary": "Fix login bug", "issue_type": "Bug", "priority": "High"}'
npx tsx skills/issues/update_issue.ts '{"issue_key": "PROJ-123", "summary": "Updated title", "labels": ["backend"]}'
npx tsx skills/issues/transition_issue.ts '{"issue_key": "PROJ-123", "transition_id": "31"}'
npx tsx skills/issues/add_comment.ts '{"issue_key": "PROJ-123", "body": "Fixed in latest commit"}'
npx tsx skills/issues/list_comments.ts '{"issue_key": "PROJ-123"}'
npx tsx skills/issues/list_transitions.ts '{"issue_key": "PROJ-123"}'
npx tsx skills/issues/add_worklog.ts '{"issue_key": "PROJ-123", "time_spent": "2h", "comment": "Code review"}'
npx tsx skills/issues/assign_issue.ts '{"issue_key": "PROJ-123", "assignee": "patrick.henry"}'
```

### GitHub Issues

```bash
npx tsx skills/issues/get_issue.ts '{"issue_key": "your-org/your-repo#42", "provider": "github"}'
npx tsx skills/issues/search_issues.ts '{"jql": "is:open label:bug", "provider": "github"}'
npx tsx skills/issues/create_issue.ts '{"project_key": "your-org/your-repo", "summary": "Fix login bug", "provider": "github"}'
npx tsx skills/issues/update_issue.ts '{"issue_key": "your-org/your-repo#42", "summary": "Updated title", "provider": "github"}'
npx tsx skills/issues/transition_issue.ts '{"issue_key": "your-org/your-repo#42", "state": "closed", "provider": "github"}'
npx tsx skills/issues/add_comment.ts '{"issue_key": "your-org/your-repo#42", "body": "Fixed in latest commit", "provider": "github"}'
npx tsx skills/issues/list_comments.ts '{"issue_key": "your-org/your-repo#42", "provider": "github"}'
npx tsx skills/issues/list_transitions.ts '{"issue_key": "your-org/your-repo#42", "provider": "github"}'
npx tsx skills/issues/add_worklog.ts '{"issue_key": "your-org/your-repo#42", "time_spent": "2h", "provider": "github"}'
npx tsx skills/issues/assign_issue.ts '{"issue_key": "your-org/your-repo#42", "assignee": "patrick-henry", "provider": "github"}'
```

### Linear

```bash
npx tsx skills/issues/get_issue.ts '{"issue_key": "ENG-123", "provider": "linear"}'
npx tsx skills/issues/search_issues.ts '{"jql": "state:started", "provider": "linear"}'
npx tsx skills/issues/create_issue.ts '{"project_key": "ENG", "summary": "Fix login bug", "provider": "linear"}'
npx tsx skills/issues/update_issue.ts '{"issue_key": "ENG-123", "summary": "Updated title", "provider": "linear"}'
npx tsx skills/issues/transition_issue.ts '{"issue_key": "ENG-123", "state": "In Progress", "provider": "linear"}'
npx tsx skills/issues/add_comment.ts '{"issue_key": "ENG-123", "body": "Fixed in latest commit", "provider": "linear"}'
npx tsx skills/issues/list_comments.ts '{"issue_key": "ENG-123", "provider": "linear"}'
npx tsx skills/issues/list_transitions.ts '{"issue_key": "ENG-123", "provider": "linear"}'
npx tsx skills/issues/add_worklog.ts '{"issue_key": "ENG-123", "time_spent": "2h", "provider": "linear"}'
npx tsx skills/issues/assign_issue.ts '{"issue_key": "ENG-123", "assignee": "patrick", "provider": "linear"}'
```

## Skill Name Remapping

Some unified skill names are remapped to provider-specific names:

| Unified Skill | GitHub Backend | Linear Backend |
|---------------|---------------|----------------|
| `transition_issue` | `update_issue_state` | `update_issue_state` |
| `list_transitions` | `list_labels` | `list_workflow_states` |

All other skills use their unified name as-is across all providers.

## Debugging

Set `ISSUES_DEBUG=1` to enable verbose logging from the router:

```bash
ISSUES_DEBUG=1 npx tsx skills/issues/get_issue.ts '{"issue_key": "PROJ-123"}'
```

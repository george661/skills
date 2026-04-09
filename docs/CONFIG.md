# Configuration Reference

All environment variables recognized by skills.

## Provider Selection

| Name | Required When | Default | Description |
|------|--------------|---------|-------------|
| `ISSUE_TRACKER` | Always | `jira` | Issue tracker backend: `jira`, `github`, `linear` |
| `VCS_PROVIDER` | Always | `bitbucket` | Version control backend: `bitbucket`, `github` |
| `CI_PROVIDER` | CI skills used | `concourse` | CI/CD backend: `concourse`, `github_actions` |

## Core Settings

| Name | Required When | Default | Description |
|------|--------------|---------|-------------|
| `TENANT_PROJECT` | Always | — | Primary project key (e.g., `PROJ`, `ENG`) |
| `JIRA_PROJECT_KEYS` | ISSUE_TRACKER=jira | — | Comma-separated Jira project keys (alternative to TENANT_PROJECT) |
| `PROJECT_ROOT` | Always | — | Absolute path to project root directory |
| `TENANT` | Always | — | Tenant identifier for multi-tenant deployments |
| `TENANT_NAMESPACE` | Always | same as TENANT | Memory namespace |

## Jira (ISSUE_TRACKER=jira)

| Name | Required When | Default | Description |
|------|--------------|---------|-------------|
| `JIRA_HOST` | ISSUE_TRACKER=jira | — | Jira instance hostname (e.g., `org.atlassian.net`) |
| `JIRA_USERNAME` | ISSUE_TRACKER=jira | — | Jira account email |
| `JIRA_API_TOKEN` | ISSUE_TRACKER=jira | — | Jira API token |
| `JIRA_PROTOCOL` | ISSUE_TRACKER=jira | `https` | Protocol for Jira API requests |

## GitHub (ISSUE_TRACKER=github or VCS_PROVIDER=github)

| Name | Required When | Default | Description |
|------|--------------|---------|-------------|
| `GITHUB_TOKEN` | github provider | — | GitHub personal access token or app token |
| `GITHUB_OWNER` | github provider | — | GitHub org or user that owns the repos |
| `GITHUB_API_URL` | github provider | `https://api.github.com` | GitHub API base URL (for GHES) |

## Linear (ISSUE_TRACKER=linear)

| Name | Required When | Default | Description |
|------|--------------|---------|-------------|
| `LINEAR_API_KEY` | ISSUE_TRACKER=linear | — | Linear API key |
| `LINEAR_TEAM_KEY` | ISSUE_TRACKER=linear | — | Linear team identifier |

## Bitbucket (VCS_PROVIDER=bitbucket)

| Name | Required When | Default | Description |
|------|--------------|---------|-------------|
| `BITBUCKET_WORKSPACE` | VCS_PROVIDER=bitbucket | — | Bitbucket workspace slug |
| `BITBUCKET_USERNAME` | VCS_PROVIDER=bitbucket | — | Bitbucket username |
| `BITBUCKET_TOKEN` | VCS_PROVIDER=bitbucket | — | Bitbucket app password |
| `BITBUCKET_DEFAULT_BRANCH` | VCS_PROVIDER=bitbucket | `main` | Default branch name |
| `BITBUCKET_REPOSITORY_SLUGS` | VCS_PROVIDER=bitbucket | — | Comma-separated repo slugs |

## CI/CD

| Name | Required When | Default | Description |
|------|--------------|---------|-------------|
| `CI_PROVIDER` | CI skills used | `concourse` | `concourse` or `github_actions` |
| `CONCOURSE_URL` | CI_PROVIDER=concourse | — | Concourse web URL |
| `CONCOURSE_TEAM` | CI_PROVIDER=concourse | `main` | Concourse team name |

## Optional Integrations

| Name | Required When | Default | Description |
|------|--------------|---------|-------------|
| `AGENTDB_URL` | AgentDB used | — | AgentDB server URL |
| `AGENTDB_API_KEY` | AgentDB used | — | AgentDB API key |
| `SLACK_BOT_TOKEN` | Slack used | — | Slack bot OAuth token |
| `SLACK_DEFAULT_CHANNEL` | Slack used | — | Default Slack channel ID |
| `TENANT_DOMAIN_PATH` | Domain model used | — | Path to CML domain model directory |

## AWS

| Name | Required When | Default | Description |
|------|--------------|---------|-------------|
| `AWS_PROFILE` | AWS services used | `default` | AWS CLI profile name |
| `AWS_REGION` | AWS services used | `us-east-1` | AWS region |

## Daemon Settings

| Name | Required When | Default | Description |
|------|--------------|---------|-------------|
| `MAX_AGENTS_PER_REPO` | Daemon mode | `2` | Max concurrent agents per repository |
| `MAX_AGENTS_TOTAL` | Daemon mode | `6` | Max concurrent agents globally |
| `POLL_INTERVAL_MS` | Daemon mode | `60000` | Issue polling interval in ms |
| `AGENT_TIMEOUT_MS` | Daemon mode | `1800000` | Agent timeout in ms |
| `LOG_LEVEL` | Always | `info` | Logging level: `debug`, `info`, `warn`, `error` |
| `DRY_RUN` | Daemon mode | `false` | Skip actual execution |

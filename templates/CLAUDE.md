# YOUR-PROJECT Project Configuration

## Project Context

This project uses agent-powered development workflows for autonomous issue processing, implementation, and validation.

**Jira Project:** YOUR-PROJECT-KEY
**Bitbucket Workspace:** your-org
**Memory Namespace:** your-namespace

### What This Project Provides

| Component | Purpose |
|-----------|---------|
| **Workflow Commands** | `/work`, `/validate`, `/next` - full issue lifecycle automation |
| **REST API Skills** | Jira, Bitbucket, Slack integrations via direct REST calls |
| **AgentDB MCP** | Vector database for agent memory (SSE streaming) |
| **Issue Orchestration** | Automated routing via step/outcome labels |
| **Multi-Tenant Support** | Configurable for any Jira/Bitbucket project |

## Repositories

All repositories are in the `your-org` Bitbucket workspace.

### Core Infrastructure

| Repository | Description | Tech Stack |
|------------|-------------|------------|
| **issue-daemon** | Orchestrates agent tasks from Jira webhooks; includes admin dashboard | Node.js, React, AWS Lambda |
| **project-agents** | Project-specific workflow configuration (this template source) | Shell, Python, YAML |
| **base-agents** | Shared workflow components (submodule of project-agents) | Shell, Python, YAML |

### Integrations

| Repository | Type | Description |
|------------|------|-------------|
| **agentdb-mcp** | MCP Server | Vector database for agent memory (SSE streaming) |
| **jira** | REST Skills | Jira Cloud/Server integration (deprecated MCP, now REST) |
| **bitbucket** | REST Skills | Bitbucket REST API integration (deprecated MCP, now REST) |
| **slack** | REST Skills | Slack bot integration (deprecated MCP, now REST) |

> **Note:** Jira, Bitbucket, and Slack integrations have been migrated from long-running MCP servers to REST-based skills for improved reliability and reduced infrastructure costs. Only AgentDB remains as an MCP server (for SSE streaming support).

### Repository Relationships

```
project-agents/
├── base/                    ← base-agents submodule (shared commands, hooks, skills)
├── templates/CLAUDE.md      ← This file (installed to other repos)
└── scripts/install.sh       ← Installs .claude/ config to target repos

issue-daemon/
├── .claude/                 ← Installed from project-agents
├── frontend/                ← React admin dashboard
└── src/                     ← Lambda handlers, routing config

{jira,bitbucket,agentdb,slack}-mcp/
├── .claude/                 ← Installed from project-agents
└── src/                     ← MCP server implementation
```

## Workflow Commands

Use these commands for all Jira issue work. Replace `PROJ-XXX` with actual issue keys.

### Core Workflow

| Command | Purpose |
|---------|---------|
| `/work PROJ-XXX` | Full implementation workflow orchestrator |
| `/validate PROJ-XXX` | Post-deployment validation with evidence |
| `/next` | Find and start next priority issue |

### Phase Commands (called by /work)

| Command | Purpose |
|---------|---------|
| `/create-implementation-plan PROJ-XXX` | Create worktree, plan, validation criteria |
| `/implement PROJ-XXX` | TDD implementation, create PR |
| `/review <repo> <pr-id>` | Code review with inline comments |
| `/fix-pr PROJ-XXX` | Fix CI failures or review comments |
| `/resolve-pr PROJ-XXX` | Merge PR, transition to Validation |

### Issue Creation

| Command | Purpose |
|---------|---------|
| `/issue "description"` | Create Jira issue from description |
| `/bug "description"` | Report bug with evidence collection |
| `/change "description"` | Request change across multiple repos |

### Epic Management

| Command | Purpose |
|---------|---------|
| `/plan PROJ-XXX` | Create PRP (Product Requirements Plan) for Epic |
| `/validate-prp PROJ-XXX` | Validate PRP completeness |
| `/fix-prp PROJ-XXX` | Fix PRP validation issues |
| `/groom PROJ-XXX` | Create child issues from PRP |
| `/validate-groom PROJ-XXX` | Validate grooming coverage |
| `/fix-groom PROJ-XXX` | Fix grooming validation issues |

### Loop Automation

| Command | Purpose |
|---------|---------|
| `/loop:issue PROJ-XXX` | Work single issue through completion |
| `/loop:epic PROJ-XXX` | Work all issues in an Epic |
| `/loop:backlog` | Process entire backlog in priority order |

### Analysis

| Command | Purpose |
|---------|---------|
| `/garden` | Analyze backlog for relevancy, accuracy, readiness |
| `/sequence` | Determine optimal issue sequencing |
| `/audit <URL>` | Role-based UI compliance testing |
| `/investigate` | Investigate CloudWatch alarms |

**Full command reference:** See `base/docs/COMMANDS.md`

## Environment Setup

### Prerequisites

- Node.js 18+
- Git with SSH access to Bitbucket
- AWS CLI configured with appropriate profiles
- Claude Code CLI

### Project Root

Set `PROJECT_ROOT` to your project checkout location:

```bash
export PROJECT_ROOT=/path/to/project
```

### AWS Configuration

Project infrastructure is deployed to AWS account `YOUR_AWS_ACCOUNT_ID` (dev-profile).

| Profile | Account ID | Purpose |
|---------|------------|---------|
| `dev-profile` | YOUR_AWS_ACCOUNT_ID | Project infrastructure (issue-daemon, MCP servers) |

**Always use the correct AWS profile:**

```bash
# Set for session
export AWS_PROFILE=${AWS_PROFILE_DEV}

# Or prefix commands
AWS_PROFILE=${AWS_PROFILE_DEV} aws s3 ls
AWS_PROFILE=${AWS_PROFILE_DEV} terraform plan
```

### Clone All Repositories

```bash
export PROJECT_ROOT=/path/to/project
mkdir -p "$PROJECT_ROOT"
cd "$PROJECT_ROOT"

# Core repositories
git clone git@bitbucket.org:your-org/issue-daemon.git
git clone git@bitbucket.org:your-org/project-agents.git

# MCP servers
git clone git@bitbucket.org:your-org/jira.git
git clone git@bitbucket.org:your-org/bitbucket.git
git clone git@bitbucket.org:your-org/agentdb-mcp.git
git clone git@bitbucket.org:your-org/slack.git

# Initialize base-agents submodule
cd "$PROJECT_ROOT/project-agents"
git submodule update --init --recursive
```

### Install Agent Configuration

After cloning, install the workflow configuration to each repository:

```bash
cd "$PROJECT_ROOT/project-agents"
./scripts/install.sh "$PROJECT_ROOT/issue-daemon"
./scripts/install.sh "$PROJECT_ROOT/jira"
./scripts/install.sh "$PROJECT_ROOT/bitbucket"
./scripts/install.sh "$PROJECT_ROOT/agentdb-mcp"
./scripts/install.sh "$PROJECT_ROOT/slack"
```

This copies `.claude/` (commands, hooks, skills) to each repository.

## Cross-Repository Coordination

### Working Across Repos

Project issues often span multiple repositories. When working on an issue:

1. **Identify affected repos** from the issue description or implementation plan
2. **Work in the primary repo** where the main change occurs
3. **Create linked PRs** in dependent repos if needed
4. **Reference the same issue key** (e.g., `PROJ-123`) in all commit messages

### Repository Dependencies

```
issue-daemon
├── depends on: agentdb (MCP), REST skills (Jira, Bitbucket, Slack)
└── consumes: project-agents (workflow configuration)

project-agents
├── contains: base-agents (submodule with REST skills)
└── installs to: all other project repos

agentdb
└── standalone MCP server (SSE streaming for real-time memory)
```

### Credentials Configuration

Credentials are stored in `~/.claude/settings.json` under the `credentials` section:

```json
{
  "credentials": {
    "jira": {
      "host": "yourcompany.atlassian.net",
      "username": "your.email@company.com",
      "apiToken": "your-api-token"
    },
    "bitbucket": {
      "workspace": "your-org",
      "username": "your-username",
      "token": "your-app-password",
      "default_branch": "main"
    },
    "slack": {
      "botToken": "xoxb-your-bot-token",
      "defaultChannel": "C1234567890"
    }
  },
  "mcpServers": {
    "agentdb": {
      "url": "https://YOUR_AGENTDB_URL/sse",
      "headers": { "X-Api-Key": "your-api-key" }
    }
  }
}
```

**Credential Fallback Order:**
1. Environment variables (e.g., `JIRA_API_TOKEN`, `BITBUCKET_TOKEN`)
2. `~/.claude/settings.json` → `credentials.{service}`
3. `~/.claude/settings.json` → `mcpServers.{service}-mcp` (legacy)
4. AWS Secrets Manager (for AgentDB only)

### Memory Namespace

All memory operations use namespace `your-namespace`:

| Key Pattern | Purpose |
|-------------|---------|
| `impl-PROJ-XXX` | Implementation plan |
| `pr-PROJ-XXX` | PR URL and number |
| `done-PROJ-XXX` | Completion evidence |
| `loop-state-PROJ-XXX` | Loop automation state |

**Fallback when agentdb is unavailable:**

If agentdb cannot be reached, write memory entries to the repository's `docs/recovery/` folder for later processing:

```bash
# Example: store implementation plan when agentdb is down
docs/recovery/impl-PROJ-123.json

# Format
{
  "namespace": "your-namespace",
  "key": "impl-PROJ-123",
  "value": { ... },
  "timestamp": "2025-01-28T12:00:00Z"
}
```

Recovery files are processed and synced to agentdb when connectivity is restored.

## REST Skills (Primary Integration Method)

Jira, Bitbucket, and Slack integrations use REST-based executable skills.

### Skills Location

Skills are installed to each repo's `.claude/skills/` directory by the tenant's `install.sh` script. The source is `base-agents/.claude/skills/` which is copied to target repos during installation.

**Installation flow:**
```
base-agents/.claude/skills/{integration}/  →  target-repo/.claude/skills/{integration}/
```

If skills are missing from a repo, re-run the install script from the tenant's agents repo (e.g., project-agents, agents):
```bash
./scripts/install.sh $PROJECT_ROOT/<target-repo>
```

### Usage

**Run from the repo where skills are installed:**

```bash
# Jira operations
npx tsx .claude/skills/jira/search_issues.ts '{"jql": "project = PROJ", "max_results": 5}'
npx tsx .claude/skills/jira/get_issue.ts '{"issue_key": "PROJ-123"}'
npx tsx .claude/skills/jira/create_issue.ts '{"project_key": "PROJ", "summary": "New task", "issue_type": "Task"}'
npx tsx .claude/skills/jira/transition_issue.ts '{"issue_key": "PROJ-123", "transition_id": "31"}'

# Bitbucket operations
npx tsx .claude/skills/bitbucket/list_pipelines.ts '{"repo_slug": "issue-daemon"}'
npx tsx .claude/skills/bitbucket/list_pull_requests.ts '{"repo_slug": "jira"}'
npx tsx .claude/skills/bitbucket/get_pipeline_step_log.ts '{"repo_slug": "jira", "pipeline_uuid": "...", "step_uuid": "..."}'

# Slack notifications
npx tsx .claude/skills/slack/send_message.ts '{"text": "Build complete", "channel": "C123"}'
```

### AgentDB (MCP - SSE Streaming)

AgentDB uses MCP for real-time SSE streaming support:

```typescript
// Use MCP tools for AgentDB
mcp__agentdb__reflexion_store_episode({
  session_id: "s1",
  task: "test",
  reward: 0.9,
  success: true
})

mcp__agentdb__pattern_search({
  task: "implement feature",
  k: 5
})
```

### Available Skills

| Integration | Type | Skills | Purpose |
|-------------|------|--------|---------|
| jira | REST | 29 | Issue management, sprints, comments, transitions |
| bitbucket | REST | 33 | PRs, pipelines, branches, commits |
| slack | REST | 1 | Send messages |
| agentdb | MCP | 6 | Memory storage, pattern search, health checks |

Skills load credentials from `~/.claude/settings.json` automatically.

### When to Use REST Skills vs AgentDB MCP

| Use REST Skills (Jira/Bitbucket/Slack) | Use AgentDB MCP |
|----------------------------------------|-----------------|
| All issue tracking operations | Memory storage/retrieval |
| PR and pipeline management | Pattern search |
| Notifications | Real-time streaming |
| Batch operations in scripts | Cross-session memory |

---

## Development Standards

### API Call Efficiency

When using REST-based skills (Jira, Bitbucket, Slack), always request only needed fields:

```typescript
// Good - selective fields via REST skill
import { jiraRequest } from '.claude/skills/jira/jira-client.js';

const issues = await jiraRequest('GET', '/rest/api/3/search', {
  jql: "project = PROJ AND status = 'To Do'",
  fields: ["key", "summary", "status", "priority"]
});

// For AgentDB (still MCP), use mcp__ tools
mcp__agentdb__pattern_search({
  task: "similar task description",
  k: 5
})
```

For programmatic operations, suppress notifications:

```typescript
await jiraRequest('POST', `/rest/api/3/issue/PROJ-123/transitions`, {
  transition: { id: "31" }
}, { notifyUsers: false });
```

> **Note:** Jira, Bitbucket, and Slack use REST skills (`.claude/skills/{tool}-mcp/`). Only AgentDB uses MCP tools (`mcp__agentdb__*`).

### Code Standards

- **Files under 500 lines** - Split larger files into modules
- **No files in root** - Use `/src`, `/tests`, `/docs`, `/scripts`
- **Remove console.log** - Clean up debug statements before commit
- **Fix tests before moving on** - Never skip or comment out tests

### Naming

- **No adjective names** - Don't use `improved`, `better`, `fixed`, `real` in names
- **Replace directly** - If something needs fixing, fix it in place

### Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| Skip workflow commands | Use `/work`, `/validate`, `/next` |
| Commit with failing tests | Fix tests first |
| Create files in root | Use appropriate subdirectories |
| Fetch all MCP fields | Use selective field queries |
| Write markdown progress docs | Store in agentdb (or `docs/recovery/`) |
| Add time estimates | Focus on what, not when |
| Skip `/create-implementation-plan` | Always plan before implementing |
| Run `/resolve-pr` with failing CI | Fix CI first with `/fix-pr` |

### Testing

- **Page Object Model (POM)** for UI tests
- **TDD cycle**: RED → GREEN → REFACTOR → COMMIT
- **Local validation** before creating PR: lint, typecheck, tests

## Quick Reference

### Workflow at a Glance

```
/next                              # Find next priority issue
    ↓
/work PROJ-XXX                     # Start full workflow
    ↓
/create-implementation-plan        # Plan, worktree, validation criteria
    ↓
/implement                         # TDD, local validation, create PR
    ↓
[CI Pipeline]
    ├─ PASS → /resolve-pr          # Merge, transition to Validation
    └─ FAIL → /fix-pr              # Fix and retry
    ↓
/validate                          # Evidence collection, transition to Done
```

### Epic Planning Flow

```
/plan PROJ-100           # Create PRP document
    ↓
/validate-prp PROJ-100   # Check PRP completeness
    ├─ PASS → /groom PROJ-100
    └─ FAIL → /fix-prp PROJ-100 → retry validate-prp
    ↓
/groom PROJ-100          # Create child issues from PRP
    ↓
/validate-groom PROJ-100 # Verify coverage and dependencies
    ├─ PASS → Ready for sprint
    └─ FAIL → /fix-groom PROJ-100 → retry validate-groom
```

### Command Cheat Sheet

```
┌─────────────────────────────────────────────────────────────┐
│                 WORKFLOW QUICK REFERENCE               │
├─────────────────────────────────────────────────────────────┤
│ START WORK        │ /work PROJ-123                          │
│ PLAN ONLY         │ /create-implementation-plan PROJ-123    │
│ IMPLEMENT ONLY    │ /implement PROJ-123                     │
│ REVIEW PR         │ /review issue-daemon 42                 │
│ FIX CI/COMMENTS   │ /fix-pr PROJ-123                        │
│ MERGE PR          │ /resolve-pr PROJ-123                    │
│ VALIDATE          │ /validate PROJ-123                      │
├─────────────────────────────────────────────────────────────┤
│ PLAN EPIC         │ /plan PROJ-100                          │
│ VALIDATE PRP      │ /validate-prp PROJ-100                  │
│ FIX PRP           │ /fix-prp PROJ-100                       │
│ GROOM EPIC        │ /groom PROJ-100                         │
│ VALIDATE GROOM    │ /validate-groom PROJ-100                │
│ FIX GROOM         │ /fix-groom PROJ-100                     │
├─────────────────────────────────────────────────────────────┤
│ LOOP ISSUE        │ /loop:issue PROJ-123                    │
│ LOOP EPIC         │ /loop:epic PROJ-100                     │
│ LOOP BACKLOG      │ /loop:backlog                           │
├─────────────────────────────────────────────────────────────┤
│ REPORT BUG        │ /bug "description"                      │
│ CREATE ISSUE      │ /issue "description"                    │
│ FIND NEXT         │ /next                                   │
│ AUDIT URL         │ /audit https://url                      │
└─────────────────────────────────────────────────────────────┘
```

### Session Start Checklist

1. Verify AWS profile: `aws sts get-caller-identity --profile ${AWS_PROFILE_DEV}`
2. Check for active work: `project = PROJ AND status = "In Progress"`
3. Check for validation: `project = PROJ AND status = Validation`
4. Find next priority: `/next`

---

*Managed by project-agents. Initial setup: `./scripts/install.sh <target-repo>`. Updates: `./scripts/update.sh`. Run from `$PROJECT_ROOT/project-agents/`.*

# Tenant Context Skill

This skill provides tenant-specific configuration for all agent operations. It ensures commands and workflows use the correct namespace, project, and VCS settings for the current tenant.

## Environment Variables

These are set by the `load-tenant-config.py` hook at session start:

| Variable | Description | Example |
|----------|-------------|---------|
| `TENANT_ID` | Tenant identifier | `acme`, `widgets` |
| `TENANT_NAMESPACE` | Memory namespace | `acme`, `widgets` |
| `TENANT_PROJECT` | Primary Jira project key | `PROJ`, `ENG` |
| `TENANT_VCS` | VCS provider | `bitbucket`, `github` |
| `TENANT_WORKSPACE` | VCS workspace/org | `your-org` |
| `TENANT_REPOS` | Comma-separated repo list | `api-service,frontend-app` |
| `TENANT_BASE_BRANCH` | Default base branch | `main` |
| `TENANT_BRANCH_PREFIX` | Agent branch prefix | `agent/` |
| `TENANT_RUNTIME` | Agent runtime type | `ecs`, `local` |
| `TENANT_JIRA_HOST` | Jira instance host | `your-org.atlassian.net` |

## Memory Operations

**ALWAYS use the tenant namespace for memory operations:**

```javascript
// Store to tenant-scoped memory
npx tsx .claude/skills/agentdb/reflexion_store_episode.ts({
  namespace: "${TENANT_NAMESPACE}",
  key: "impl-${TENANT_PROJECT}-123",
  value: "implementation plan content"
})

// Retrieve from tenant-scoped memory
npx tsx .claude/skills/agentdb/pattern_search.ts({
  namespace: "${TENANT_NAMESPACE}",
  key: "impl-${TENANT_PROJECT}-123"
})
```

**Memory Key Patterns:**
- Implementation plans: `impl-${TENANT_PROJECT}-{issueNumber}`
- PR information: `pr-${TENANT_PROJECT}-{issueNumber}`
- Checkpoints: `checkpoint-${TENANT_PROJECT}-{issueNumber}-{phase}`
- Session costs: `session-costs-${TENANT_PROJECT}-{issueNumber}`
- Project overview: `project-overview`
- Repository structure: `repo-structure`

## Jira Queries

**ALWAYS scope JQL queries to the tenant project:**

```sql
-- Find issues to work on
project = ${TENANT_PROJECT} AND status = 'To Do' ORDER BY priority DESC

-- Find issues in validation
project = ${TENANT_PROJECT} AND status = 'VALIDATION' AND labels NOT IN (step:validating)

-- Find issues by label
project = ${TENANT_PROJECT} AND labels = 'repo-api-service'
```

## VCS Operations

**Check the provider before VCS operations:**

### Bitbucket (when TENANT_VCS = "bitbucket")
```bash
npx tsx .claude/skills/bitbucket-mcp/create_pull_request.ts '{
  "workspace": "${TENANT_WORKSPACE}",
  "repo_slug": "repository-name",
  "title": "${TENANT_PROJECT}-123: Feature description",
  "source_branch": "${TENANT_BRANCH_PREFIX}${TENANT_PROJECT}-123",
  "destination_branch": "${TENANT_BASE_BRANCH}"
}'
```

### GitHub (when TENANT_VCS = "github")
```javascript
mcp__github__create_pull_request({
  owner: "${TENANT_WORKSPACE}",
  repo: "repository-name",
  title: "${TENANT_PROJECT}-123: Feature description",
  head: "${TENANT_BRANCH_PREFIX}${TENANT_PROJECT}-123",
  base: "${TENANT_BASE_BRANCH}"
})
```

## Issue Key Patterns

**Use tenant project in issue references:**

- Branch names: `${TENANT_BRANCH_PREFIX}${TENANT_PROJECT}-123`
- PR titles: `${TENANT_PROJECT}-123: Description`
- Commit messages: `${TENANT_PROJECT}-123: What changed`
- Labels: `repo-{reponame}`, `step:{phase}`

## Checkpoint Keys

**Include tenant project in checkpoint identifiers:**

```python
# Checkpoint key format
checkpoint_key = f"checkpoint-{TENANT_PROJECT}-{issue_number}-{phase}"

# Example: checkpoint-PROJ-123-implementing
# Example: checkpoint-PROJ-456-validating
```

## Repository Discovery

**Use TENANT_REPOS for repository filtering:**

```python
import os

# Get list of tenant repositories
repos = os.environ.get('TENANT_REPOS', '').split(',')
repos = [r.strip() for r in repos if r.strip()]

# Example: ['api-service', 'frontend-app', 'auth-service', 'project-docs']
```

## Runtime Awareness

**Check TENANT_RUNTIME for execution context:**

- `ecs`: Running as ECS Fargate task (production)
- `local`: Running as local process (development)
- `remote`: Running via remote endpoint

```python
runtime = os.environ.get('TENANT_RUNTIME', 'local')
if runtime == 'ecs':
    # Production behavior - full logging, metrics
    pass
elif runtime == 'local':
    # Development behavior - verbose output, local paths
    pass
```

## Loading Tenant Config

If tenant config is not already loaded, run:

```bash
# Load config and export to current shell
eval $(python .claude/hooks/load-tenant-config.py)

# Or source the generated env file
source /tmp/tenant.env
```

## Verification

To verify tenant context is loaded:

```bash
echo "Tenant: $TENANT_ID"
echo "Namespace: $TENANT_NAMESPACE"
echo "Project: $TENANT_PROJECT"
echo "VCS: $TENANT_VCS ($TENANT_WORKSPACE)"
```

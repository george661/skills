---
name: session-init
description: Shared initialization skill for all agent commands - loads tenant config, memory, initializes swarm, sets up cost tracking
---

# Session Initialization Skill

This skill provides consistent initialization for all agent commands. Commands should invoke this skill in Phase 0 before their domain-specific work.

## 0.0 Tenant Context Loading (ALWAYS FIRST)

**Load tenant configuration to set namespace, project, and VCS context:**

If running locally or tenant env vars not set:
```bash
# Load tenant config from AppConfig/local file
eval $(python3 .claude/hooks/load-tenant-config.py)
# Or source pre-generated env file
source /tmp/tenant.env
```

**Required tenant environment variables:**
| Variable | Description | Example |
|----------|-------------|---------|
| `TENANT_NAMESPACE` | Memory namespace | `acme`, `widgets` |
| `TENANT_PROJECT` | Jira project key | `PROJ`, `ENG` |
| `TENANT_VCS` | VCS provider | `bitbucket`, `github` |
| `TENANT_WORKSPACE` | VCS workspace | `your-org` |

**Verify tenant context:**
```bash
echo "Tenant: $TENANT_ID | Project: $TENANT_PROJECT | Namespace: $TENANT_NAMESPACE"
```

See `.claude/skills/tenant-context.skill.md` for full tenant configuration reference.

---

## Usage

Commands include this via reference:
```markdown
> Skill reference: [session-init](.claude/skills/session-init.skill.md)
```

Then in Phase 0:
```markdown
## Phase 0: Session Initialization

**Execute session-init skill with configuration:**
- swarm_topology: "hierarchical" | "mesh" | "star" | "none"
- swarm_agents: [...agent configs...] | []
- agentdb_query: "query string" | null
- step_label: "step:planning" | null
- cost_guardrails: true | false
```

---

## 0.1 Memory Context Loading (ALWAYS)

**Load the project persistent memory to avoid re-explaining project context:**

```typescript
// Batch ALL memory retrievals in ONE call
npx tsx .claude/skills/agentdb({ action: "list", namespace: "${TENANT_NAMESPACE}" })
```

**Expected keys loaded:**
- `project-overview` - the project business model and marketplace concept
- `repo-structure` - Repository purposes and relationships
- `critical-distinction` - Session vs authentication clarity
- `release-target` - Current release date and MVP scope
- `dev-patterns` - Development patterns and conventions
- `working-directory` - Current working directory context

**If keys missing, command should NOT re-explain the project context. Instead:**
```typescript
npx tsx .claude/skills/agentdb/pattern_search.ts({
  pattern: "project|repo|release",
  namespace: "${TENANT_NAMESPACE}",
  limit: 10
})
```

---

## 0.2 Parallel Task Coordination (CONDITIONAL)

**Use the Task tool for parallel operations ONLY if command needs parallel coordination.**

### When to use parallel tasks:
| Use Case | Strategy | Max Tasks |
|----------|----------|-----------|
| Complex analysis (planning, validation) | hierarchical | 4-6 |
| Parallel issue creation (grooming) | mesh | 6-8 |
| Pipeline monitoring (CI/CD) | star | 3-4 |
| Simple sequential work | none | 0 |

### Agent Type Reference:
| Agent Type | Purpose |
|------------|---------|
| `researcher` | Information gathering, code analysis |
| `architecture` | System design, cross-impact analysis |
| `coder` | Implementation, code generation |
| `tester` | Test creation, validation |
| `reviewer` | Code review, quality checks |
| `documenter` | PRP writing, documentation |
| `coordinator` | Batch orchestration |
| `monitor` | Pipeline monitoring |
| `optimizer` | Performance optimization |

---

## 0.3 AgentDB Memory Search (CONDITIONAL)

**Query AgentDB for related context ONLY if command needs historical context.**

```typescript
// Only if agentdb_query !== null
mcp__agentdb__recall_query({
  query_id: "{command}-{issue_key}",
  query: "{agentdb_query}"
})
```

### When to use AgentDB:
| Command Type | Use AgentDB? | Query Focus |
|--------------|--------------|-------------|
| Planning (/plan) | YES | Prior PRPs, architectural decisions |
| Creation (/issue, /bug) | YES | Similar issues, duplicates |
| Analysis (/audit, /sequence) | YES | Historical patterns |
| Implementation (/implement) | NO | Focus on current issue |
| Simple workflow (/next) | NO | Current state only |

---

## 0.4 Step Label Management (CONDITIONAL)

**Set step label ONLY if command is part of trackable workflow.**

### Step label lifecycle:

```bash
# Set label at command start (if step_label !== null)
# This is done via Jira update, not memory

# Pattern for adding step label:
npx tsx .claude/skills/jira-mcp/edit_issue.ts '{
  "issue_key": "{ISSUE_KEY}",
  "fields": {
    "labels": [/* existing labels */, "{step_label}"]
  }
}'
```

### Available step labels:
| Label | Command | Description |
|-------|---------|-------------|
| `step:planning` | /plan, /create-implementation-plan | Issue being planned |
| `step:grooming` | /groom | Epic being groomed |
| `step:implementing` | /implement | Code being written |
| `step:awaiting-ci` | /implement (end) | Waiting for CI pipeline |
| `step:reviewing` | /review | PR under review |
| `step:fixing-pr` | /fix-pr | Addressing CI/review issues |
| `step:merging` | /resolve-pr | PR being merged |
| `step:validating` | /validate | Post-deploy validation |

### Querying by step label:
```bash
npx tsx .claude/skills/jira-mcp/search_issues.ts '{
  "jql": "project = ${TENANT_PROJECT} AND labels = '\''step_label'\''",
  "fields": ["key", "summary", "status"]
}'
```

---

## 0.5 Cost Guardrails (CONDITIONAL)

**Track session costs ONLY for expensive operations.**

### Cost thresholds:
| Level | Tokens | Action |
|-------|--------|--------|
| Normal | < 20 | Continue |
| Warning | 20-49 | Log warning, continue |
| Block | >= 50 | Stop, checkpoint, exit |

### Cost tracking pattern:

```typescript
// Only if cost_guardrails === true
// Track at phase transitions

// Store cost checkpoint
npx tsx .claude/skills/agentdb({
  action: "store",
  namespace: "${TENANT_NAMESPACE}",
  key: "cost-{command}-{issue_key}",
  value: JSON.stringify({
    phase: "{current_phase}",
    tokens: "{estimated_tokens}",
    timestamp: new Date().toISOString()
  })
})
```

---

## 0.6 Token Optimization Reminders

**These patterns apply to ALL commands:**

1. **Batch MCP calls** - Make multiple calls in single messages
2. **Use selective fields** - Only request needed Jira fields
3. **Use Task tool** - For research instead of multiple Grep/Glob
4. **Store decisions** - Cache in memory to avoid re-computation

### Field selection examples:

```bash
# GOOD - selective
npx tsx .claude/skills/jira-mcp/search_issues.ts '{
  "jql": "...",
  "fields": ["key", "summary", "status", "priority"]
}'

# BAD - fetches everything
npx tsx .claude/skills/jira-mcp/search_issues.ts '{"jql": "..."}'
```

---

## 0.7 Pattern Learning Setup (CONDITIONAL)

**Initialize pattern learning for commands that train models.**

```typescript
// Record command start for pattern learning
npx tsx .claude/skills/agentdb/reflexion_store_episode.ts '{
  "session_id": "${TENANT_NAMESPACE}",
  "task": "{command}-{issue_key}-start",
  "reward": 0.0,
  "success": false
}'
```

---

## Configuration Matrix

| Command | Swarm | AgentDB | Step Label | Cost Guards | Pattern Learning |
|---------|-------|---------|------------|-------------|------------------|
| /plan | hierarchical | YES | step:planning | NO | YES |
| /groom | mesh | YES | step:grooming | NO | YES |
| /validate-prp | hierarchical | YES | - | NO | YES |
| /validate-groom | hierarchical | YES | - | NO | YES |
| /work | none | NO | step:* | YES | NO |
| /create-impl-plan | hierarchical | YES | step:planning | YES | NO |
| /implement | none | NO | step:implementing | NO | NO |
| /review | none | NO | step:reviewing | NO | NO |
| /validate | star | NO | step:validating | YES | YES |
| /next | none | NO | - | NO | YES |
| /issue | none | YES | - | NO | YES |
| /bug | none | YES | - | NO | YES |
| /audit | hierarchical | YES | - | NO | YES |
| /sequence | hierarchical | NO | - | NO | YES |

---

## Anti-Patterns

- Loading memory without checking for existing context = TOKEN WASTE
- Initializing swarm for simple sequential work = OVERHEAD
- Using AgentDB for every command = UNNECESSARY LATENCY
- Setting step labels without cleaning up = STALE LABELS
- Skipping cost guardrails on expensive operations = RUNAWAY COSTS

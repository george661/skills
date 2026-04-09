---
name: index-repos
description: Index project repositories into CodeGraphContext for code graph analysis
agent-invokeable: true
---

# Index Repos

Index the project project repositories into CodeGraphContext's graph database for code relationship analysis, dead code detection, complexity analysis, and call chain exploration.

## Usage

```
/index-repos                    # Index all core repos
/index-repos api-service             # Index a single repo
/index-repos api-service frontend-app      # Index specific repos
/index-repos --status           # Show indexed repos and status
/index-repos --force            # Force re-index (overwrite existing)
```

## Prerequisites

- `cgc` CLI installed (`pip3 install codegraphcontext`)
- Neo4j running via Docker (`docker start neo4j`) OR FalkorDB Lite working
- CodeGraphContext configured (`~/.codegraphcontext/.env`)

Check availability:

```bash
command -v cgc >/dev/null 2>&1 && echo "cgc: OK" || echo "cgc: NOT INSTALLED"
docker ps --filter name=neo4j --format '{{.Status}}' 2>/dev/null || echo "Neo4j: NOT RUNNING"
```

## Core Repositories

These repositories contain meaningful code worth indexing:

| Repository | Language | Description |
|------------|----------|-------------|
| `api-service` | Go | Core business logic - sessions, tokens, marketplace |
| `frontend-app` | TypeScript/React | Frontend marketplace UI |
| `auth-service` | Go | Platform authentication (Cognito, JWT) |
| `agents` | TypeScript | Workflow configuration and skills |
| `e2e-tests` | TypeScript/Playwright | E2E browser testing |
| `publisher-sdk` | TypeScript | Publisher integration SDK |

Optional (small, index if needed):

| Repository | Language | Description |
|------------|----------|-------------|
| `cli-tool` | Go | Command-line tooling |
| `jwt-demo` | Go | JWT demo/testing service |
| `test-data` | Mixed | Test fixtures |
| `migrations` | SQL/Go | Database migrations |

## Execution

### Step 1: Verify Prerequisites

```bash
# Check cgc is available
cgc --version 2>&1

# Check database is accessible
cgc list 2>&1
```

If Neo4j is not running:

```bash
docker start neo4j 2>/dev/null || \
  docker run -d --name neo4j -p 7474:7474 -p 7687:7687 \
    -e NEO4J_AUTH=neo4j/codegraph123 neo4j:latest
```

### Step 2: Index Repositories

For each requested repository (or all core repos if none specified):

```bash
# Set database backend
export DEFAULT_DATABASE=neo4j

# Index a single repo
cgc index ${PROJECT_ROOT}/<repo-name>

# Force re-index
cgc index ${PROJECT_ROOT}/<repo-name> --force
```

Index repos **sequentially** (not in parallel) to avoid Neo4j write conflicts.

### Step 3: Verify

```bash
cgc list
```

Expected output shows each repo as a separate entry with its path.

## Status Check

To show current indexing status without re-indexing:

```bash
cgc list 2>&1
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `cgc: command not found` | Run `pip3 install codegraphcontext` |
| Neo4j connection refused | Run `docker start neo4j` |
| FalkorDB worker failed | Check `libomp` is installed: `brew install libomp` |
| Indexing very slow | Check `.gitignore` excludes `node_modules`, `vendor`, `dist` |
| Duplicate graph entries | Run `cgc clean` then re-index with `--force` |

## Integration

This skill is standalone and does not participate in the `/work` or `/validate` workflows. Run it:

- After initial `agents` install
- After major refactors that change code structure
- When switching branches with significant changes
- When CodeGraphContext MCP tools return stale results

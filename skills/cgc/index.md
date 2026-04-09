---
name: cgc:index
description: Index a directory into the code graph
---

# index

Index a local directory into the code graph database. Traverses source files and builds a graph of functions, types, imports, and their relationships.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | No | Directory to index. Defaults to current directory. |
| `force` | boolean | No | Re-index even if the repo is already indexed. |
| `database` | string | No | Path to an alternate graph database file. |

## Example

```bash
npx tsx ~/.claude/skills/cgc/index.ts '{"path": "$PROJECT_ROOT/frontend-app"}'
npx tsx ~/.claude/skills/cgc/index.ts '{"path": "$PROJECT_ROOT/lambda-functions", "force": true}'
```

## Notes

- Default path is current directory.
- Use `force: true` to re-index already indexed repos.
- Indexing is incremental by default; force re-indexes from scratch.

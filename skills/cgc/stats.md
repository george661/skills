---
name: cgc:stats
description: Show indexing statistics for the database or a specific repository
---

# stats

Display node and edge counts for the graph database. Optionally scope to a single repository.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | No | Repository path to scope stats to. |
| `database` | string | No | Path to an alternate graph database file. |

## Example

```bash
npx tsx ~/.claude/skills/cgc/stats.ts '{}'
npx tsx ~/.claude/skills/cgc/stats.ts '{"path": "$PROJECT_ROOT/lambda-functions"}'
```

## Notes

- Without `path` shows global stats across all indexed repositories.
- With `path` shows per-repo node counts (functions, types, imports, etc.).

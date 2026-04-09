---
name: cgc:delete
description: Remove a repository from the graph
---

# delete

Remove a single repository or wipe the entire graph database.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | No | Path of the repository to remove. |
| `all` | boolean | No | Wipe the entire database when `true`. |
| `database` | string | No | Path to an alternate graph database file. |

## Example

```bash
npx tsx ~/.claude/skills/cgc/delete.ts '{"path": "$PROJECT_ROOT/frontend-app"}'
npx tsx ~/.claude/skills/cgc/delete.ts '{"all": true}'
```

## Notes

- Either `path` or `all: true` must be provided.
- Do not provide `path` when using `all: true`.
- Run `cgc:clean` after deletion to reclaim graph space.

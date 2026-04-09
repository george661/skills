---
name: cgc:unwatch
description: Stop watching a directory
---

# unwatch

Stop an active file watcher for the given directory path.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | Yes | Directory path to stop watching. |
| `database` | string | No | Path to an alternate graph database file. |

## Example

```bash
npx tsx ~/.claude/skills/cgc/unwatch.ts '{"path": "$PROJECT_ROOT/lambda-functions"}'
```

## Notes

- `path` must match exactly what was passed to `cgc:watch`.
- Use `cgc:watching` first to see the exact paths currently registered.

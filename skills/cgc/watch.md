---
name: cgc:watch
description: Watch a directory for changes and auto-reindex
---

# watch

Start a file watcher on a directory. The graph is automatically updated whenever source files change.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | No | Directory to watch. Defaults to current directory. |
| `database` | string | No | Path to an alternate graph database file. |

## Example

```bash
npx tsx ~/.claude/skills/cgc/watch.ts '{"path": "$PROJECT_ROOT/lambda-functions"}'
```

## Notes

- This is a long-running background process. The skill starts the watcher and returns.
- Use `cgc:watching` to list active watchers.
- Use `cgc:unwatch` to stop a watcher.

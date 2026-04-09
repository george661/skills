---
name: fly:prune_worker
description: Remove a stalled, landing, landed, or retiring worker from the Concourse database.
---

# prune_worker

Remove a non-operational worker from the Concourse cluster. Running workers cannot be pruned (they will just re-register). Use this to clean up workers that are permanently gone.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `worker` | string | No | Specific worker name to prune |
| `all_stalled` | boolean | No | Prune all stalled workers |

One of `worker` or `all_stalled` must be provided.

## Example

```bash
# Prune a specific worker
npx tsx ~/.claude/skills/fly/prune_worker.ts '{"worker": "worker-1"}'

# Prune all stalled workers
npx tsx ~/.claude/skills/fly/prune_worker.ts '{"all_stalled": true}'
```

## Response

```json
{
  "success": true,
  "target": "my-concourse",
  "worker": "worker-1",
  "message": "pruned worker worker-1"
}
```

## Notes

- Only works on workers in stalled, landing, landed, or retiring state
- Running workers cannot be pruned — they will re-register immediately
- Pruning releases container/volume references held by the worker
- Use this when a worker has been permanently removed or will not return

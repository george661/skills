---
name: fly:land_worker
description: Gracefully drain a worker for temporary maintenance.
---

# land_worker

Initiate a graceful worker shutdown. The worker finishes all non-interruptible builds, then enters LANDED state. Use this for planned maintenance windows.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `worker` | string | Yes | Worker name to land |

## Example

```bash
npx tsx ~/.claude/skills/fly/land_worker.ts '{"worker": "worker-1"}'
```

## Response

```json
{
  "success": true,
  "target": "my-concourse",
  "worker": "worker-1",
  "message": "landing worker worker-1"
}
```

## Notes

- Worker transitions: RUNNING -> LANDING (draining) -> LANDED (idle)
- Non-interruptible builds will complete before the worker reaches LANDED
- After maintenance, restart the worker process — it re-registers as RUNNING
- Check progress with `fly workers` — look for state changes

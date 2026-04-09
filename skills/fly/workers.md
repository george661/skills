---
name: fly:workers
description: List registered Concourse workers with state, container count, and metadata.
---

# workers

List all registered workers on the Concourse target. Shows worker state (running, stalled, landing, landed, retiring), container count, platform, tags, team, version, and age.

## Parameters

No parameters required.

## Example

```bash
npx tsx ~/.claude/skills/fly/workers.ts '{}'
```

## Response

```json
{
  "target": "my-concourse",
  "count": 2,
  "workers": [
    {
      "name": "worker-1",
      "state": "running",
      "containers": 5,
      "platform": "linux",
      "tags": [],
      "team": "",
      "version": "2.5"
    }
  ]
}
```

## Notes

- Workers in "stalled" state have stopped heartbeating and are not accepting work
- Use `prune_worker` to remove stalled workers from the database
- Use `land_worker` for graceful temporary shutdown
- See the `fly-operations` skill for worker troubleshooting flowcharts

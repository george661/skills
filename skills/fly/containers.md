---
name: fly:containers
description: List active containers across all Concourse workers.
---

# containers

List all active containers across all workers. Useful for identifying containers to intercept, checking what's running on a specific worker, and diagnosing stuck workers.

## Parameters

No parameters required.

## Example

```bash
npx tsx ~/.claude/skills/fly/containers.ts '{}'
```

## Response

```json
{
  "target": "my-concourse",
  "count": 12,
  "containers": [
    {
      "id": "abc123",
      "worker_name": "worker-1",
      "type": "task",
      "pipeline_name": "my-app",
      "job_name": "build",
      "build_name": "42",
      "build_id": 42,
      "step_name": "run-tests",
      "attempt": ""
    }
  ]
}
```

## Notes

- Containers persist after FAILED builds for debugging (use `fly intercept`)
- Containers are removed after successful build completion
- Filter by worker name in the output to see what's running on a specific worker

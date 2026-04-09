---
name: fly:watch_build
description: Watch or retrieve the output of a specific Concourse build by its ID.
---

# watch_build

Watch or retrieve the full console output of a specific Concourse build. If the build is in progress, streams the output until completion. If the build has finished, returns the complete output.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `build_id` | number | Yes | The numeric build ID to watch |

## Example

```bash
# Watch/get output of build 42
npx tsx ~/.claude/skills/fly/watch_build.ts '{"build_id": 42}'
```

## Response

```json
{
  "target": "my-concourse",
  "build_id": 42,
  "output": "fetching image...\nrunning script...\ntest suite passed\n"
}
```

## Notes

- For in-progress builds, this command blocks until the build completes
- For completed builds, returns the full output immediately
- Build IDs can be obtained from `list_builds` or from the output of `trigger_job`
- The output includes all task step logs concatenated
- Use this for debugging failed builds or verifying successful ones

---
name: concourse:get_build
description: Get detailed information about a specific build.
---

# get_build

Get detailed information about a specific build by its ID, including status, duration, and associated job/pipeline info.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `build_id` | number | Yes | The numeric build ID |

## Example

```typescript
// Get build details
npx tsx ~/.claude/skills/concourse/get_build.ts '{"build_id": 12345}'
```

## Notes

- Build IDs are returned when triggering jobs or listing builds
- Build statuses include: pending, started, succeeded, failed, errored, aborted
- Returns build metadata including id, name, status, start_time, end_time, and job/pipeline references

---
name: fly:abort_build
description: Cancel a running Concourse build.
---

# abort_build

Cancel a running build. Can specify by global build ID or by job + build number.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `build_id` | number | No | Global build ID (use without job) |
| `job` | string | No | Job name in `PIPELINE/JOB` format (use with build_number) |
| `build_number` | number | No | Build number within the job (use with job) |

Either `build_id` or both `job` and `build_number` must be provided. Do not provide both.

## Example

```bash
# By global build ID
npx tsx ~/.claude/skills/fly/abort_build.ts '{"build_id": 12345}'

# By job + build number
npx tsx ~/.claude/skills/fly/abort_build.ts '{"job": "my-app/build", "build_number": 3}'
```

## Response

```json
{
  "success": true,
  "target": "my-concourse",
  "message": "build 12345 was aborted"
}
```

## Notes

- Aborting a build triggers `on_abort` hooks if configured
- Does not delete the build — it remains in history with "aborted" status
- Use this to unblock serial jobs stuck behind a hanging build

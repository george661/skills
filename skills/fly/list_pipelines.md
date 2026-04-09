---
name: fly:list_pipelines
description: List all pipelines on the Concourse target.
---

# list_pipelines

List all pipelines available on the configured Concourse target. Returns pipeline names, team ownership, and paused status.

## Parameters

This function takes no parameters.

## Example

```bash
# List all pipelines
npx tsx ~/.claude/skills/fly/list_pipelines.ts '{}'
```

## Response

```json
{
  "target": "my-concourse",
  "count": 3,
  "pipelines": [
    {
      "id": 1,
      "name": "my-app",
      "paused": false,
      "public": false,
      "archived": false,
      "team_name": "main"
    }
  ]
}
```

## Notes

- Returns all pipelines the authenticated user has access to
- Paused pipelines will not trigger builds until unpaused
- Archived pipelines are read-only and no longer active

---
name: jira:add_worklog
description: Add a worklog entry to an issue.
---

# add_worklog

Add a worklog entry to track time spent on a Jira issue. This is useful for time tracking and project management.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `issue_key` | string | Yes | The issue key (e.g., "PROJ-123") |
| `time_spent` | string | Yes | Time spent in Jira format (e.g., "2h 30m", "1d") |
| `comment` | string | No | Optional work description |
| `started` | string | No | When the work started (ISO 8601 format) |

## Example

```typescript
// Log 2 hours of work
npx tsx ~/.claude/skills/jira/add_worklog.ts '{"issue_key": "PROJ-123", "time_spent": "2h"}'

// Log work with a comment and start time
npx tsx ~/.claude/skills/jira/add_worklog.ts '{"issue_key": "PROJ-123", "time_spent": "4h 30m", "comment": "Implemented feature X", "started": "2025-01-28T09:00:00.000Z"}'
```

## Notes

- Time format supports: weeks (w), days (d), hours (h), minutes (m)
- Examples: "1w", "2d", "4h", "30m", "1d 4h 30m"
- If `started` is not provided, the current time is used

---
name: jira:transition_issue
description: Transition an issue to a new status (e.g., move from "To Do" to "In Progress").
---

# transition_issue

Transition a Jira issue to a new status using a workflow transition.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `issue_key` | string | Yes | The issue key (e.g., "PROJ-123") |
| `transition_id` | string | Yes | The transition ID (get from list_transitions) |
| `comment` | string | No | Optional comment to add with the transition |
| `notify_users` | boolean | No | Whether to send email notification (default: true) |

## Example

```typescript
// Transition an issue to a new status
npx tsx ~/.claude/skills/jira/transition_issue.ts '{"issue_key": "PROJ-123", "transition_id": "21"}'

// Transition with a comment
npx tsx ~/.claude/skills/jira/transition_issue.ts '{"issue_key": "PROJ-123", "transition_id": "31", "comment": "Moving to In Progress"}'

// Transition without notifications (for automation)
npx tsx ~/.claude/skills/jira/transition_issue.ts '{"issue_key": "PROJ-123", "transition_id": "41", "notify_users": false}'
```

## Notes

- Use `list_transitions` first to get available transition IDs for the issue
- Set `notify_users: false` for automated transitions to avoid spamming users
- The transition ID is a string, not a number

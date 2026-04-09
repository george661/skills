---
name: jira:list_sprints
description: List all sprints for a board.
---

# list_sprints

List all sprints for a specific Jira board, with optional filtering by state.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `board_id` | number | Yes | The board ID |
| `state` | string | No | Filter by sprint state ("active", "closed", "future") |
| `start_at` | number | No | Starting index for pagination (default: 0) |
| `max_results` | number | No | Maximum results to return |

## Example

```typescript
// List all sprints for a board
npx tsx ~/.claude/skills/jira/list_sprints.ts '{"board_id": 1}'

// List only active sprints
npx tsx ~/.claude/skills/jira/list_sprints.ts '{"board_id": 1, "state": "active"}'

// List future sprints
npx tsx ~/.claude/skills/jira/list_sprints.ts '{"board_id": 1, "state": "future"}'
```

## Notes

- Use `list_boards` to find the board ID
- Sprint states: "active" (current sprint), "closed" (completed), "future" (planned)
- Use sprint ID from results with `get_sprint`, `get_sprint_issues`, and `add_issue_to_sprint`

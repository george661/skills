---
name: jira:get_board
description: Get details about a specific board.
---

# get_board

Get detailed information about a specific Jira board (Scrum or Kanban).

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `board_id` | number | Yes | The board ID |

## Example

```typescript
// Get board details
npx tsx ~/.claude/skills/jira/get_board.ts '{"board_id": 1}'
```

## Notes

- Use `list_boards` to find board IDs
- Returns board name, type, and associated project information

---
name: jira:list_boards
description: List all boards (Scrum and Kanban). Optionally filter by project.
---

# list_boards

List all Jira boards (Scrum and Kanban) with optional filtering by project, type, or name.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_key` | string | No | Filter by project key |
| `board_type` | string | No | Filter by board type ("scrum" or "kanban") |
| `name` | string | No | Filter by board name (partial match) |
| `start_at` | number | No | Starting index for pagination (default: 0) |
| `max_results` | number | No | Maximum results to return |

## Example

```typescript
// List all boards
npx tsx ~/.claude/skills/jira/list_boards.ts '{}'

// List boards for a specific project
npx tsx ~/.claude/skills/jira/list_boards.ts '{"project_key": "PROJ"}'

// List only Scrum boards
npx tsx ~/.claude/skills/jira/list_boards.ts '{"board_type": "scrum"}'
```

## Notes

- Use the board ID from results with `get_board`, `list_sprints`, and `get_sprint_issues`
- Results are paginated for large instances

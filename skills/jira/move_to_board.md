# move_to_board

Register issues with a Jira Kanban board so they appear in board columns instead of just the backlog.

## Why This Is Needed

Issues created via the REST API (`/rest/api/3/issue`) are not automatically ranked on Kanban boards. Without a board rank, they show in the backlog view but not in their mapped column on the main board. This call registers them with the agile board and assigns ranks.

## Examples

### Move issues to the platform board (board ID 35)
```bash
npx tsx ~/.claude/skills/jira/move_to_board.ts '{"board_id": 35, "issue_keys": ["PROJ-100", "PROJ-101", "PROJ-102"]}'
```

## Finding Board IDs

```bash
npx tsx ~/.claude/skills/jira/list_boards.ts '{"project_key": "${PROJECT_KEY}"}'
```

## Known Board IDs

| Project | Board | ID |
|---------|-------|----|
| the project | project board | 35 |

## Return Format

Returns `{"success": true}` on success.

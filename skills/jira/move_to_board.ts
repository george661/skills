#!/usr/bin/env npx tsx
// move_to_board - Register issues with a Jira Kanban board so they appear in board columns (not just backlog).
// API-created issues lack board rank; this call assigns rank so the board renders them.
import { jiraRequest } from './jira-client.js';

interface Input {
  board_id: number;
  issue_keys: string[];
}

async function execute(input: Input) {
  return jiraRequest('POST', `/rest/agile/1.0/board/${input.board_id}/issue`, {
    issues: input.issue_keys,
  });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

#!/usr/bin/env npx tsx
// get_board - Get details about a specific board.
import { jiraRequest } from './jira-client.js';

interface Input {
  board_id: number;
}

async function execute(input: Input) {
  return jiraRequest('GET', `/rest/agile/1.0/board/${input.board_id}`);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

#!/usr/bin/env npx tsx
// list_sprints - List all sprints for a board.
import { jiraRequest } from './jira-client.js';

interface Input {
  board_id: number;
  state?: string;
  start_at?: number;
  max_results?: number;
}

async function execute(input: Input) {
  const params = new URLSearchParams();
  if (input.state) params.append('state', input.state);
  if (input.start_at !== undefined) params.append('startAt', String(input.start_at));
  if (input.max_results !== undefined) params.append('maxResults', String(input.max_results));

  const query = params.toString();
  const path = `/rest/agile/1.0/board/${input.board_id}/sprint${query ? `?${query}` : ''}`;

  return jiraRequest('GET', path);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

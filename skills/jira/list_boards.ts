#!/usr/bin/env npx tsx
// list_boards - List all boards (Scrum and Kanban). Optionally filter by project.
import { jiraRequest } from './jira-client.js';

interface Input {
  project_key?: string;
  board_type?: string;
  name?: string;
  start_at?: number;
  max_results?: number;
}

async function execute(input: Input) {
  const params = new URLSearchParams();
  if (input.project_key) params.append('projectKeyOrId', input.project_key);
  if (input.board_type) params.append('type', input.board_type);
  if (input.name) params.append('name', input.name);
  if (input.start_at !== undefined) params.append('startAt', String(input.start_at));
  if (input.max_results !== undefined) params.append('maxResults', String(input.max_results));

  const query = params.toString();
  const path = `/rest/agile/1.0/board${query ? `?${query}` : ''}`;

  return jiraRequest('GET', path);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

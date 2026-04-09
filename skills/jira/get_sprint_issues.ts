#!/usr/bin/env npx tsx
// get_sprint_issues - Get all issues in a sprint.
import { jiraRequest } from './jira-client.js';

interface Input {
  board_id: number;
  sprint_id: number;
  jql?: string;
  start_at?: number;
  max_results?: number;
  fields?: string;
}

async function execute(input: Input) {
  const params = new URLSearchParams();
  if (input.jql) params.append('jql', input.jql);
  if (input.start_at !== undefined) params.append('startAt', String(input.start_at));
  if (input.max_results !== undefined) params.append('maxResults', String(input.max_results));
  if (input.fields) params.append('fields', input.fields);

  const query = params.toString();
  const path = `/rest/agile/1.0/board/${input.board_id}/sprint/${input.sprint_id}/issue${query ? `?${query}` : ''}`;

  return jiraRequest('GET', path);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

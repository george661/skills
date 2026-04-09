#!/usr/bin/env npx tsx
// search_users - Search for users by name or email.
import { jiraRequest } from './jira-client.js';

interface Input {
  query: string;
  start_at?: number;
  max_results?: number;
}

async function execute(input: Input) {
  const params = new URLSearchParams();
  params.append('query', input.query);
  if (input.start_at !== undefined) params.append('startAt', String(input.start_at));
  if (input.max_results !== undefined) params.append('maxResults', String(input.max_results));

  return jiraRequest('GET', `/rest/api/3/user/search?${params.toString()}`);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

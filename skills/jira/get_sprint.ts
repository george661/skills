#!/usr/bin/env npx tsx
// get_sprint - Get details about a specific sprint.
import { jiraRequest } from './jira-client.js';

interface Input {
  sprint_id: number;
}

async function execute(input: Input) {
  return jiraRequest('GET', `/rest/agile/1.0/sprint/${input.sprint_id}`);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

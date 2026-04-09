#!/usr/bin/env npx tsx
// list_transitions - List available transitions for an issue (workflow states it can move to).
import { jiraRequest } from './jira-client.js';

interface Input {
  issue_key: string;
}

async function execute(input: Input) {
  return jiraRequest('GET', `/rest/api/3/issue/${input.issue_key}/transitions`);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

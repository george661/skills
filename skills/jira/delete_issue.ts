#!/usr/bin/env npx tsx
// delete_issue - Delete an issue from Jira. Use with caution.
import { jiraRequest } from './jira-client.js';

interface Input {
  issue_key: string;
}

async function execute(input: Input) {
  return jiraRequest('DELETE', `/rest/api/3/issue/${input.issue_key}`);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

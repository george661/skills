#!/usr/bin/env npx tsx
// list_comments - List all comments on an issue.
import { jiraRequest } from './jira-client.js';

interface Input {
  issue_key: string;
}

async function execute(input: Input) {
  return jiraRequest('GET', `/rest/api/3/issue/${input.issue_key}/comment`);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

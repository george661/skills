#!/usr/bin/env npx tsx
// assign_issue - Assign or unassign an issue to a user.
import { jiraRequest } from './jira-client.js';

interface Input {
  issue_key: string;
  account_id?: string;
}

async function execute(input: Input) {
  return jiraRequest('PUT', `/rest/api/3/issue/${input.issue_key}/assignee`, { accountId: input.account_id ?? null });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

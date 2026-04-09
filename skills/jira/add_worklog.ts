#!/usr/bin/env npx tsx
// add_worklog - Add a worklog entry to an issue.
import { jiraRequest } from './jira-client.js';

interface Input {
  issue_key: string;
  time_spent: string;
  comment?: string;
  started?: string;
}

async function execute(input: Input) {
  const requestBody: Record<string, unknown> = {
    timeSpent: input.time_spent
  };
  if (input.comment) {
    requestBody.comment = {
      type: 'doc',
      version: 1,
      content: [{ type: 'paragraph', content: [{ type: 'text', text: input.comment }] }]
    };
  }
  if (input.started) {
    requestBody.started = input.started;
  }
  return jiraRequest('POST', `/rest/api/3/issue/${input.issue_key}/worklog`, requestBody);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

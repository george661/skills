#!/usr/bin/env npx tsx
// add_issue_to_sprint - Add an issue to a sprint.
import { jiraRequest } from './jira-client.js';

interface Input {
  issue_key: string;
  sprint_id: number;
}

async function execute(input: Input) {
  return jiraRequest('POST', `/rest/agile/1.0/sprint/${input.sprint_id}/issue`, {
    issues: [input.issue_key]
  });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

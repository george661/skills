#!/usr/bin/env npx tsx
// add_comment - Add a comment to an issue.
import { jiraRequest } from './jira-client.js';

interface Input {
  issue_key: string;
  body: string;
}

async function execute(input: Input) {
  const body = {
    body: {
      type: 'doc',
      version: 1,
      content: [{ type: 'paragraph', content: [{ type: 'text', text: input.body }] }],
    },
  };

  return jiraRequest('POST', `/rest/api/3/issue/${input.issue_key}/comment`, body);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

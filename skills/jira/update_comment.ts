#!/usr/bin/env npx tsx
// update_comment - Update an existing comment.
import { jiraRequest } from './jira-client.js';

interface Input {
  issue_key: string;
  comment_id: string;
  body: string;
}

async function execute(input: Input) {
  const requestBody = {
    body: {
      type: 'doc',
      version: 1,
      content: [{ type: 'paragraph', content: [{ type: 'text', text: input.body }] }]
    }
  };
  return jiraRequest('PUT', `/rest/api/3/issue/${input.issue_key}/comment/${input.comment_id}`, requestBody);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

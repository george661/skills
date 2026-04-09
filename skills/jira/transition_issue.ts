#!/usr/bin/env npx tsx
// transition_issue - Transition an issue to a new status (e.g., move from "To Do" to "In Progress").
import { jiraRequest } from './jira-client.js';

interface Input {
  issue_key: string;
  transition_id: string;
  comment?: string;
  notify_users?: boolean;
}

async function execute(input: Input) {
  const body: Record<string, unknown> = {
    transition: { id: input.transition_id },
  };

  if (input.comment) {
    body.update = {
      comment: [{
        add: {
          body: {
            type: 'doc',
            version: 1,
            content: [{ type: 'paragraph', content: [{ type: 'text', text: input.comment }] }],
          },
        },
      }],
    };
  }

  return jiraRequest('POST', `/rest/api/3/issue/${input.issue_key}/transitions`, body);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

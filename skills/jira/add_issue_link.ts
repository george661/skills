#!/usr/bin/env npx tsx
// add_issue_link - Create a link between two Jira issues (e.g., "Blocks", "Relates", "Duplicate").
import { jiraRequest } from './jira-client.js';

interface Input {
  inward_issue_key: string;
  outward_issue_key: string;
  link_type: string; // e.g., "Blocks", "Relates", "Cloners", "Duplicate"
  comment?: string;
}

async function execute(input: Input) {
  if (!input.inward_issue_key) throw new Error('inward_issue_key is required');
  if (!input.outward_issue_key) throw new Error('outward_issue_key is required');
  if (!input.link_type) throw new Error('link_type is required');

  const body: Record<string, unknown> = {
    type: { name: input.link_type },
    inwardIssue: { key: input.inward_issue_key },
    outwardIssue: { key: input.outward_issue_key },
  };

  if (input.comment) {
    body.comment = {
      body: {
        type: 'doc',
        version: 1,
        content: [{ type: 'paragraph', content: [{ type: 'text', text: input.comment }] }],
      },
    };
  }

  // POST /rest/api/3/issueLink returns 201 with empty body on success
  await jiraRequest('POST', '/rest/api/3/issueLink', body);
  return {
    success: true,
    inward: input.inward_issue_key,
    outward: input.outward_issue_key,
    type: input.link_type,
  };
}

const input = JSON.parse(process.argv[2] || '{}');
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => {
    console.error(JSON.stringify({ error: e.message }));
    process.exit(1);
  });

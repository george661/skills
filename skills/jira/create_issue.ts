#!/usr/bin/env npx tsx
// create_issue - Create a new issue in Jira.
import { jiraRequest, getJiraCostFieldId } from './jira-client.js';

interface Input {
  project_key: string;
  summary: string;
  description?: string;
  issue_type: string;
  priority?: string;
  assignee_account_id?: string;
  labels?: string[];
  parent?: string;
  cost?: number;
  notify_users?: boolean;
}

async function execute(input: Input) {
  const fields: Record<string, unknown> = {
    project: { key: input.project_key },
    summary: input.summary,
    issuetype: { name: input.issue_type },
  };

  if (input.description) {
    fields.description = {
      type: 'doc',
      version: 1,
      content: [{ type: 'paragraph', content: [{ type: 'text', text: input.description }] }],
    };
  }
  if (input.priority) {
    fields.priority = { name: input.priority };
  }
  if (input.assignee_account_id) {
    fields.assignee = { accountId: input.assignee_account_id };
  }
  if (input.labels) {
    fields.labels = input.labels;
  }
  if (input.parent) {
    fields.parent = { key: input.parent };
  }
  if (input.cost !== undefined) {
    const costFieldId = getJiraCostFieldId();
    if (costFieldId) {
      fields[costFieldId] = input.cost;
    }
  }

  return jiraRequest('POST', '/rest/api/3/issue', { fields });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

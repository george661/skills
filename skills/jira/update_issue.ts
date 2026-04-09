#!/usr/bin/env npx tsx
// update_issue - Update an existing issue. Only provide fields you want to change.
import { jiraRequest, getJiraCostFieldId } from './jira-client.js';

interface Input {
  issue_key: string;
  summary?: string;
  description?: string;
  priority?: string;
  labels?: string[];
  parent?: string;
  cost?: number;
  notify_users?: boolean;
}

async function execute(input: Input) {
  const fields: Record<string, unknown> = {};

  if (input.summary) {
    fields.summary = input.summary;
  }
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

  const params = input.notify_users === false ? '?notifyUsers=false' : '';
  return jiraRequest('PUT', `/rest/api/3/issue/${input.issue_key}${params}`, { fields });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

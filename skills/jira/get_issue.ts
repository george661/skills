#!/usr/bin/env npx tsx
// get_issue - Get detailed information about a specific issue by its key.
import { jiraRequest, getDefaultFields } from './jira-client.js';

interface Input {
  issue_key: string;
  fields?: string;
  expand?: string;
}

async function execute(input: Input) {
  const params = new URLSearchParams();
  if (input.fields) {
    params.set('fields', input.fields);
  } else {
    const defaults = getDefaultFields('get_issue');
    if (defaults) {
      params.set('fields', defaults);
    }
  }
  if (input.expand) {
    params.set('expand', input.expand);
  }
  const query = params.toString();
  const path = `/rest/api/3/issue/${input.issue_key}${query ? `?${query}` : ''}`;
  return jiraRequest('GET', path);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

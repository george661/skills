#!/usr/bin/env npx tsx
// search_issues - Search for issues using JQL (Jira Query Language). Returns paginated results.
import { jiraRequest, getDefaultFields } from './jira-client.js';

interface Input {
  jql: string;
  start_at?: number;
  max_results?: number;
  fields?: string[];
}

async function execute(input: Input) {
  const params = new URLSearchParams({
    jql: input.jql,
    startAt: String(input.start_at || 0),
    maxResults: String(input.max_results || 50),
  });
  if (input.fields) {
    params.set('fields', input.fields.join(','));
  } else {
    const defaults = getDefaultFields('search_issues');
    if (defaults) {
      params.set('fields', defaults);
    }
  }
  // Use the new /search/jql endpoint (old /search was deprecated)
  return jiraRequest('GET', `/rest/api/3/search/jql?${params}`);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

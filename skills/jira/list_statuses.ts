#!/usr/bin/env npx tsx
// list_statuses - List all available issue statuses.
import { jiraRequest } from './jira-client.js';

interface Input {

}

async function execute(_input: Input) {
  return jiraRequest('GET', '/rest/api/3/status');
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

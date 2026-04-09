#!/usr/bin/env npx tsx
// get_project - Get detailed information about a specific Jira project.
import { jiraRequest } from './jira-client.js';

interface Input {
  project_key: string;
}

async function execute(input: Input) {
  return jiraRequest('GET', `/rest/api/3/project/${input.project_key}`);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

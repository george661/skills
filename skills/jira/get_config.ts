#!/usr/bin/env npx tsx
// get_config - Get the current MCP server configuration (host, projects).
import { getJiraCredentials } from './jira-client.js';

interface Input {

}

async function execute(_input: Input) {
  const creds = getJiraCredentials();
  return {
    host: creds.host,
    username: creds.username,
    baseUrl: `https://${creds.host}`,
  };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

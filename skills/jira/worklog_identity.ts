#!/usr/bin/env npx tsx
// worklog_identity - Write a rich identity worklog entry for a command phase.
import { jiraRequest } from './jira-client.js';
import * as os from 'os';

interface Input {
  issue_key: string;
  phase: string;    // e.g. "start", "complete"
  command: string;  // e.g. "/work", "/validate", "/review"
  message: string;  // narrative summary
}

async function execute(input: Input) {
  const sessionId = process.env.CLAUDE_SESSION_ID || 'unknown-session';
  const hostname = os.hostname();
  const identity = `${sessionId}@${hostname}`;
  const timestamp = new Date().toISOString();

  const body = `[agent: ${identity}]
${input.phase}: ${input.command} on ${input.issue_key}
${input.message}
timestamp: ${timestamp}`;

  const requestBody = {
    timeSpent: '1m',
    comment: {
      type: 'doc',
      version: 1,
      content: [{ type: 'paragraph', content: [{ type: 'text', text: body }] }],
    },
  };

  return jiraRequest('POST', `/rest/api/3/issue/${input.issue_key}/worklog`, requestBody);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

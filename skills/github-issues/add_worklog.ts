#!/usr/bin/env npx tsx
// add_worklog - Log time spent on a GitHub issue.
// GitHub has no native worklog API; this posts a comment with a [Time: ...] prefix.
import { githubRequest, getGitHubCredentials } from './github-client.js';

interface Input {
  owner?: string;
  repo: string;
  issue_number: number;
  time_spent: string;
  comment?: string;
}

async function execute(input: Input) {
  const { defaultOwner } = getGitHubCredentials();
  const owner = input.owner || defaultOwner;

  const body = input.comment
    ? `[Time: ${input.time_spent}] ${input.comment}`
    : `[Time: ${input.time_spent}]`;

  return githubRequest('POST', `/repos/${owner}/${input.repo}/issues/${input.issue_number}/comments`, {
    body,
  });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

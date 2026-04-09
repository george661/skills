#!/usr/bin/env npx tsx
// add_comment - Add a comment to a GitHub issue.
import { githubRequest, getGitHubCredentials } from './github-client.js';

interface Input {
  owner?: string;
  repo: string;
  issue_number: number;
  body: string;
}

async function execute(input: Input) {
  const { defaultOwner } = getGitHubCredentials();
  const owner = input.owner || defaultOwner;

  return githubRequest('POST', `/repos/${owner}/${input.repo}/issues/${input.issue_number}/comments`, {
    body: input.body,
  });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

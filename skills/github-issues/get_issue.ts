#!/usr/bin/env npx tsx
// get_issue - Get detailed information about a specific GitHub issue by number.
import { githubRequest, getGitHubCredentials } from './github-client.js';

interface Input {
  owner?: string;
  repo: string;
  issue_number: number;
}

async function execute(input: Input) {
  const { defaultOwner } = getGitHubCredentials();
  const owner = input.owner || defaultOwner;
  return githubRequest('GET', `/repos/${owner}/${input.repo}/issues/${input.issue_number}`);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

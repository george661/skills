#!/usr/bin/env npx tsx
// assign_issue - Add assignees to a GitHub issue.
import { githubRequest, getGitHubCredentials } from './github-client.js';

interface Input {
  owner?: string;
  repo: string;
  issue_number: number;
  assignees: string[];
}

async function execute(input: Input) {
  const { defaultOwner } = getGitHubCredentials();
  const owner = input.owner || defaultOwner;

  return githubRequest('POST', `/repos/${owner}/${input.repo}/issues/${input.issue_number}/assignees`, {
    assignees: input.assignees,
  });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

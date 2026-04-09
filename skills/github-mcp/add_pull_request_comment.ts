#!/usr/bin/env npx tsx
// add_pull_request_comment - Add a general comment to a pull request (issue comment).
import { githubApi, resolveOwner } from './github-client.js';

interface Input {
  owner?: string;
  repo: string;
  pull_number: number;
  body: string;
}

async function execute(input: Input) {
  const owner = resolveOwner(input.owner);
  // General PR comments use the issues endpoint in GitHub's API
  return githubApi('POST', `/repos/${owner}/${input.repo}/issues/${input.pull_number}/comments`, {
    body: input.body,
  });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

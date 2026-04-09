#!/usr/bin/env npx tsx
// list_pull_request_comments - List all comments on a pull request (both issue comments and review comments).
import { githubApi, resolveOwner } from './github-client.js';

interface Input {
  owner?: string;
  repo: string;
  pull_number: number;
}

async function execute(input: Input) {
  const owner = resolveOwner(input.owner);

  // Fetch both issue comments and review comments in parallel
  const [issueComments, reviewComments] = await Promise.all([
    githubApi<any[]>('GET', `/repos/${owner}/${input.repo}/issues/${input.pull_number}/comments`),
    githubApi<any[]>('GET', `/repos/${owner}/${input.repo}/pulls/${input.pull_number}/comments`),
  ]);

  return {
    issue_comments: issueComments,
    review_comments: reviewComments,
    total: (issueComments?.length || 0) + (reviewComments?.length || 0),
  };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

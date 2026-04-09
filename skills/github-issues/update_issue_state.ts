#!/usr/bin/env npx tsx
// update_issue_state - Open or close a GitHub issue.
import { githubRequest, getGitHubCredentials } from './github-client.js';

interface Input {
  owner?: string;
  repo: string;
  issue_number: number;
  state: 'open' | 'closed';
  state_reason?: 'completed' | 'not_planned' | 'reopened';
}

async function execute(input: Input) {
  const { defaultOwner } = getGitHubCredentials();
  const owner = input.owner || defaultOwner;

  const payload: Record<string, unknown> = { state: input.state };
  if (input.state_reason) payload.state_reason = input.state_reason;

  return githubRequest('PATCH', `/repos/${owner}/${input.repo}/issues/${input.issue_number}`, payload);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

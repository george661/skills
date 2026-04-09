#!/usr/bin/env npx tsx
// create_issue - Create a new GitHub issue in a repository.
import { githubRequest, getGitHubCredentials } from './github-client.js';

interface Input {
  owner?: string;
  repo: string;
  title: string;
  body?: string;
  labels?: string[];
  assignees?: string[];
  milestone?: number;
}

async function execute(input: Input) {
  const { defaultOwner } = getGitHubCredentials();
  const owner = input.owner || defaultOwner;

  const payload: Record<string, unknown> = { title: input.title };
  if (input.body) payload.body = input.body;
  if (input.labels) payload.labels = input.labels;
  if (input.assignees) payload.assignees = input.assignees;
  if (input.milestone) payload.milestone = input.milestone;

  return githubRequest('POST', `/repos/${owner}/${input.repo}/issues`, payload);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

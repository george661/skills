#!/usr/bin/env npx tsx
// update_issue - Update an existing GitHub issue (title, body, labels, assignees, milestone).
import { githubRequest, getGitHubCredentials } from './github-client.js';

interface Input {
  owner?: string;
  repo: string;
  issue_number: number;
  title?: string;
  body?: string;
  labels?: string[];
  assignees?: string[];
  milestone?: number | null;
}

async function execute(input: Input) {
  const { defaultOwner } = getGitHubCredentials();
  const owner = input.owner || defaultOwner;

  const payload: Record<string, unknown> = {};
  if (input.title !== undefined) payload.title = input.title;
  if (input.body !== undefined) payload.body = input.body;
  if (input.labels !== undefined) payload.labels = input.labels;
  if (input.assignees !== undefined) payload.assignees = input.assignees;
  if (input.milestone !== undefined) payload.milestone = input.milestone;

  return githubRequest('PATCH', `/repos/${owner}/${input.repo}/issues/${input.issue_number}`, payload);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

#!/usr/bin/env npx tsx
// merge_pull_request - Merge a pull request.
import { githubApi, resolveOwner } from './github-client.js';

interface Input {
  owner?: string;
  repo: string;
  pull_number: number;
  commit_title?: string;
  commit_message?: string;
  merge_method?: 'merge' | 'squash' | 'rebase';
}

async function execute(input: Input) {
  const owner = resolveOwner(input.owner);
  const payload: Record<string, unknown> = {};
  if (input.commit_title) payload.commit_title = input.commit_title;
  if (input.commit_message) payload.commit_message = input.commit_message;
  if (input.merge_method) payload.merge_method = input.merge_method;

  return githubApi('PUT', `/repos/${owner}/${input.repo}/pulls/${input.pull_number}/merge`, payload);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

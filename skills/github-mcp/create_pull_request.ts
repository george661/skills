#!/usr/bin/env npx tsx
// create_pull_request - Create a new pull request from a feature branch.
import { githubApi, resolveOwner } from './github-client.js';

interface Input {
  owner?: string;
  repo: string;
  title: string;
  head: string;
  base?: string;
  body?: string;
  draft?: boolean;
}

async function execute(input: Input) {
  const owner = resolveOwner(input.owner);
  const payload: Record<string, unknown> = {
    title: input.title,
    head: input.head,
    base: input.base || 'main',
  };
  if (input.body) payload.body = input.body;
  if (input.draft !== undefined) payload.draft = input.draft;

  return githubApi('POST', `/repos/${owner}/${input.repo}/pulls`, payload);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

#!/usr/bin/env npx tsx
// get_pull_request_diff - Get the diff for a pull request.
import { githubApiText, resolveOwner } from './github-client.js';

interface Input {
  owner?: string;
  repo: string;
  pull_number: number;
}

async function execute(input: Input) {
  const owner = resolveOwner(input.owner);
  return githubApiText(
    'GET',
    `/repos/${owner}/${input.repo}/pulls/${input.pull_number}`,
    { 'Accept': 'application/vnd.github.v3.diff' }
  );
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(r))
  .catch((e) => { console.error(e.message); process.exit(1); });

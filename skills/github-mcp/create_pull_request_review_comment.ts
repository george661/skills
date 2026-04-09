#!/usr/bin/env npx tsx
// create_pull_request_review_comment - Add an inline review comment on a specific line.
import { githubApi, resolveOwner } from './github-client.js';

interface Input {
  owner?: string;
  repo: string;
  pull_number: number;
  body: string;
  path: string;
  line: number;
  commit_id: string;
  side?: 'LEFT' | 'RIGHT';
}

async function execute(input: Input) {
  const owner = resolveOwner(input.owner);
  const payload: Record<string, unknown> = {
    body: input.body,
    path: input.path,
    line: input.line,
    commit_id: input.commit_id,
  };
  if (input.side) payload.side = input.side;

  return githubApi(
    'POST',
    `/repos/${owner}/${input.repo}/pulls/${input.pull_number}/comments`,
    payload
  );
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

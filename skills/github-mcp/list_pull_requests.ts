#!/usr/bin/env npx tsx
// list_pull_requests - List pull requests in a repository. Filter by state.
import { githubApi, resolveOwner } from './github-client.js';

interface Input {
  owner?: string;
  repo: string;
  state?: 'open' | 'closed' | 'all';
  head?: string;
  base?: string;
  sort?: 'created' | 'updated' | 'popularity';
  direction?: 'asc' | 'desc';
  per_page?: number;
}

async function execute(input: Input) {
  const owner = resolveOwner(input.owner);
  const params = new URLSearchParams();
  if (input.state) params.set('state', input.state);
  if (input.head) params.set('head', input.head);
  if (input.base) params.set('base', input.base);
  if (input.sort) params.set('sort', input.sort);
  if (input.direction) params.set('direction', input.direction);
  if (input.per_page) params.set('per_page', String(input.per_page));

  const query = params.toString() ? `?${params}` : '';
  return githubApi('GET', `/repos/${owner}/${input.repo}/pulls${query}`);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

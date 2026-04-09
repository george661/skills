#!/usr/bin/env npx tsx
// list_labels - List all labels in a GitHub repository.
import { githubRequest, getGitHubCredentials } from './github-client.js';

interface Input {
  owner?: string;
  repo: string;
  per_page?: number;
  page?: number;
}

async function execute(input: Input) {
  const { defaultOwner } = getGitHubCredentials();
  const owner = input.owner || defaultOwner;

  const params = new URLSearchParams();
  if (input.per_page) params.set('per_page', String(input.per_page));
  if (input.page) params.set('page', String(input.page));
  const query = params.toString();

  return githubRequest('GET', `/repos/${owner}/${input.repo}/labels${query ? `?${query}` : ''}`);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

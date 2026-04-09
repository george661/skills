#!/usr/bin/env npx tsx
// list_workflow_runs - List GitHub Actions workflow runs for CI status monitoring.
import { githubApi, resolveOwner } from './github-client.js';

interface Input {
  owner?: string;
  repo: string;
  workflow_id?: string;
  branch?: string;
  event?: string;
  status?: 'queued' | 'in_progress' | 'completed';
  per_page?: number;
}

async function execute(input: Input) {
  const owner = resolveOwner(input.owner);
  const params = new URLSearchParams();
  if (input.branch) params.set('branch', input.branch);
  if (input.event) params.set('event', input.event);
  if (input.status) params.set('status', input.status);
  if (input.per_page) params.set('per_page', String(input.per_page));

  const base = input.workflow_id
    ? `/repos/${owner}/${input.repo}/actions/workflows/${input.workflow_id}/runs`
    : `/repos/${owner}/${input.repo}/actions/runs`;

  const query = params.toString() ? `?${params}` : '';
  return githubApi('GET', `${base}${query}`);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

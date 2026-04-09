#!/usr/bin/env npx tsx
// list_workflow_runs - List GitHub Actions workflow runs for a repository.
import { ghActionsRequest, getGitHubOwner } from './github-actions-client.js';

interface Input {
  owner?: string;
  repo: string;
  branch?: string;
  status?: string;
  per_page?: number;
  page?: number;
}

async function execute(input: Input) {
  const owner = input.owner || getGitHubOwner();
  const params = new URLSearchParams();
  if (input.branch) params.set('branch', input.branch);
  if (input.status) params.set('status', input.status);
  params.set('per_page', String(input.per_page || 30));
  params.set('page', String(input.page || 1));

  const qs = params.toString();
  const result: any = await ghActionsRequest(
    'GET',
    `/repos/${owner}/${input.repo}/actions/runs${qs ? `?${qs}` : ''}`
  );

  return {
    total_count: result.total_count,
    runs: (result.workflow_runs || []).map((run: any) => ({
      id: run.id,
      name: run.name,
      status: run.status,
      conclusion: run.conclusion,
      html_url: run.html_url,
      created_at: run.created_at,
      updated_at: run.updated_at,
      head_branch: run.head_branch,
      head_sha: run.head_sha,
    })),
  };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

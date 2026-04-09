#!/usr/bin/env npx tsx
// get_workflow_run - Get details of a specific GitHub Actions workflow run.
import { ghActionsRequest, getGitHubOwner } from './github-actions-client.js';

interface Input {
  owner?: string;
  repo: string;
  run_id: number;
}

async function execute(input: Input) {
  const owner = input.owner || getGitHubOwner();
  const run: any = await ghActionsRequest('GET', `/repos/${owner}/${input.repo}/actions/runs/${input.run_id}`);
  return {
    id: run.id,
    status: run.status,
    conclusion: run.conclusion,
    html_url: run.html_url,
    created_at: run.created_at,
    updated_at: run.updated_at,
    head_branch: run.head_branch,
    head_sha: run.head_sha,
  };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

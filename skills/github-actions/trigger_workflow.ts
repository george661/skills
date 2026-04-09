#!/usr/bin/env npx tsx
// trigger_workflow - Trigger a GitHub Actions workflow dispatch event.
import { ghActionsRequest, getGitHubOwner } from './github-actions-client.js';

interface Input {
  owner?: string;
  repo: string;
  workflow_id: string | number;
  ref: string;
  inputs?: Record<string, string>;
}

async function execute(input: Input) {
  const owner = input.owner || getGitHubOwner();
  await ghActionsRequest(
    'POST',
    `/repos/${owner}/${input.repo}/actions/workflows/${input.workflow_id}/dispatches`,
    { ref: input.ref, inputs: input.inputs }
  );
  // The API returns 204 No Content on success — no response body.
  return { triggered: true, workflow_id: input.workflow_id, ref: input.ref };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

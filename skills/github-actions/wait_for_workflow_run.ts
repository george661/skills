#!/usr/bin/env npx tsx
/**
 * wait_for_workflow_run.ts — Wait for a GitHub Actions workflow run to complete.
 *
 * Usage:
 *   npx tsx wait_for_workflow_run.ts '{"owner": "myorg", "repo": "myrepo", "run_id": 12345}'
 *   npx tsx wait_for_workflow_run.ts '{"owner": "myorg", "repo": "myrepo", "workflow": "ci.yml", "timeout_seconds": 600}'
 *
 * Returns:
 *   {
 *     "run": "https://github.com/owner/repo/actions/runs/12345",
 *     "success": true,
 *     "build_id": 12345,
 *     "status": "completed",
 *     "output": {
 *       "build": { "success": true, "logs": [] }
 *     }
 *   }
 */
import { ghActionsRequest } from './github-actions-client.js';

interface Input {
  owner?: string;
  repo?: string;
  run_id?: number;
  workflow?: string;
  timeout_seconds?: number;
  poll_interval?: number;
}

interface TaskOutput {
  success: boolean;
  logs: string[];
}

interface BuildResult {
  run: string;
  success: boolean;
  build_id: number;
  status: string;
  output: Record<string, TaskOutput>;
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function execute(input: Input): Promise<BuildResult> {
  const owner = input.owner || process.env.GITHUB_OWNER;
  const repo = input.repo;

  if (!owner) throw new Error('"owner" or GITHUB_OWNER env is required');
  if (!repo) throw new Error('"repo" is required');

  const timeoutSeconds = input.timeout_seconds ?? 900;
  const pollInterval = input.poll_interval ?? 30;
  const deadline = Date.now() + timeoutSeconds * 1000;

  let runId = input.run_id;

  // If run_id not provided, find the latest run for the workflow
  if (!runId) {
    const workflow = input.workflow ?? 'ci.yml';
    try {
      // Use REST API to list workflow runs
      // GET /repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs
      const runs = await ghActionsRequest<{ workflow_runs: Array<{ id: number }> }>(
        'GET',
        `/repos/${owner}/${repo}/actions/workflows/${workflow}/runs?per_page=1`
      );
      if (runs.workflow_runs.length === 0) {
        throw new Error(`No workflow runs found for ${workflow}`);
      }
      runId = runs.workflow_runs[0].id;
    } catch (err) {
      throw new Error(`Failed to find workflow run: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  // Poll until workflow run completes
  const TERMINAL = new Set(['completed', 'cancelled', 'failure', 'success', 'skipped']);

  while (Date.now() < deadline) {
    let runData: { status: string; conclusion: string | null; html_url: string };
    try {
      // Use REST API to get workflow run status
      // GET /repos/{owner}/{repo}/actions/runs/{run_id}
      runData = await ghActionsRequest<{ status: string; conclusion: string | null; html_url: string }>(
        'GET',
        `/repos/${owner}/${repo}/actions/runs/${runId}`
      );
    } catch (err) {
      throw new Error(`Failed to get workflow run status: ${err instanceof Error ? err.message : String(err)}`);
    }

    const status = runData.status ?? 'unknown';
    const conclusion = runData.conclusion ?? 'unknown';
    const url = runData.html_url ?? `https://github.com/${owner}/${repo}/actions/runs/${runId}`;

    if (TERMINAL.has(status)) {
      const success = conclusion === 'success';
      return {
        run: url,
        success,
        build_id: runId,
        status: conclusion,
        output: {
          build: {
            success,
            logs: [],
          },
        },
      };
    }

    if (Date.now() + pollInterval * 1000 > deadline) {
      throw new Error(`Timed out after ${timeoutSeconds}s waiting for ${owner}/${repo} run ${runId} (status: ${status})`);
    }

    await sleep(pollInterval * 1000);
  }

  throw new Error(`Timed out after ${timeoutSeconds}s waiting for ${owner}/${repo} run ${runId}`);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then(r => console.log(JSON.stringify(r, null, 2)))
  .catch(e => { console.error(e.message); process.exit(1); });

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
import { execSync } from 'child_process';

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
    const listCmd = `gh run list --repo ${owner}/${repo} --workflow ${workflow} --limit 1 --json databaseId`;
    try {
      const listOutput = execSync(listCmd, { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] });
      const runs = JSON.parse(listOutput);
      if (runs.length === 0) {
        throw new Error(`No workflow runs found for ${workflow}`);
      }
      runId = runs[0].databaseId;
    } catch (err) {
      throw new Error(`Failed to find workflow run: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  // Poll until workflow run completes
  const TERMINAL = new Set(['completed', 'cancelled', 'failure', 'success', 'skipped']);

  while (Date.now() < deadline) {
    const statusCmd = `gh run view ${runId} --repo ${owner}/${repo} --json status,conclusion,url`;
    let statusOutput: string;
    try {
      statusOutput = execSync(statusCmd, { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] });
    } catch (err) {
      throw new Error(`Failed to get workflow run status: ${err instanceof Error ? err.message : String(err)}`);
    }

    const runData = JSON.parse(statusOutput);
    const status = runData.status ?? 'unknown';
    const conclusion = runData.conclusion ?? 'unknown';
    const url = runData.url ?? `https://github.com/${owner}/${repo}/actions/runs/${runId}`;

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

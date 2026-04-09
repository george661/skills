#!/usr/bin/env npx tsx
// get_workflow_run_logs - Get logs from a GitHub Actions workflow run for debugging CI failures.
import { execSync } from 'child_process';
import { resolveOwner } from './github-client.js';

interface Input {
  owner?: string;
  repo: string;
  run_id: number;
  job_name?: string;
}

async function execute(input: Input) {
  const owner = resolveOwner(input.owner);

  if (input.job_name) {
    // Get logs for a specific job by name
    const jobsRaw = execSync(
      `gh api '/repos/${owner}/${input.repo}/actions/runs/${input.run_id}/jobs' --jq '.jobs[] | select(.name == "${input.job_name}") | .id'`,
      { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 15000 }
    ).trim();

    if (!jobsRaw) {
      throw new Error(`Job "${input.job_name}" not found in run ${input.run_id}`);
    }

    const logs = execSync(
      `gh api '/repos/${owner}/${input.repo}/actions/jobs/${jobsRaw}/logs'`,
      { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 15000 }
    );
    return { job_name: input.job_name, job_id: jobsRaw, logs };
  }

  // List all jobs with their conclusions, then get failed job logs
  const jobsJson = execSync(
    `gh api '/repos/${owner}/${input.repo}/actions/runs/${input.run_id}/jobs'`,
    { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 15000 }
  );
  const jobs = JSON.parse(jobsJson);

  const failedJobs = jobs.jobs?.filter((j: any) => j.conclusion === 'failure') || [];

  if (failedJobs.length === 0) {
    // No failures - return job summary
    return {
      run_id: input.run_id,
      jobs: jobs.jobs?.map((j: any) => ({
        id: j.id,
        name: j.name,
        status: j.status,
        conclusion: j.conclusion,
      })),
    };
  }

  // Get logs for failed jobs
  const results = [];
  for (const job of failedJobs.slice(0, 3)) {
    try {
      const logs = execSync(
        `gh api '/repos/${owner}/${input.repo}/actions/jobs/${job.id}/logs'`,
        { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 15000 }
      );
      results.push({ job_id: job.id, job_name: job.name, logs });
    } catch {
      results.push({ job_id: job.id, job_name: job.name, logs: '(failed to fetch logs)' });
    }
  }

  return { run_id: input.run_id, failed_jobs: results };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(typeof r === 'string' ? r : JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

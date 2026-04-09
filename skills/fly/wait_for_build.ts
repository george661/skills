#!/usr/bin/env npx tsx
/**
 * wait_for_build - Poll a Concourse job until the latest build completes or timeout.
 * Returns the final build status.
 *
 * Usage:
 *   npx tsx wait_for_build.ts '{"pipeline": "lambda-functions", "job": "pr-validate", "timeout_seconds": 600, "poll_interval": 30}'
 *
 * If "job" is omitted, auto-detects the PR validation job by searching for jobs
 * matching common patterns: pr-validate, pr-check, pr-test, validate-pr, check-pr, etc.
 *
 * Optional: pass "build_name" to wait for a specific build number instead of latest.
 */
import { flyExecJson, getFlyTarget } from './fly-client.js';

interface Input {
  pipeline: string;
  job?: string;
  build_name?: string;
  timeout_seconds?: number;
  poll_interval?: number;
}

interface Build {
  id: number;
  name: string;
  status: string;
  start_time?: number;
  end_time?: number;
  pipeline_name: string;
  job_name: string;
  team_name: string;
}

interface Job {
  id: number;
  name: string;
  pipeline_name: string;
  team_name: string;
}

/** Patterns that indicate a PR validation job, ranked by priority */
const PR_JOB_PATTERNS = [
  /^pr-validate$/i,
  /^pr-check$/i,
  /^pr-test$/i,
  /^validate-pr$/i,
  /^check-pr$/i,
  /^pr[-_]?verif/i,
  /^pr[-_]/i,
  /^pull[-_]request/i,
];

/**
 * Auto-detect the PR validation job in a pipeline by matching job names
 * against common PR job patterns.
 */
function detectPrJob(pipeline: string): string {
  let jobs: Job[];
  try {
    jobs = flyExecJson<Job[]>(['jobs', '-p', pipeline]);
  } catch {
    throw new Error(`Failed to list jobs for pipeline "${pipeline}". Verify the pipeline exists.`);
  }

  if (!Array.isArray(jobs) || jobs.length === 0) {
    throw new Error(`No jobs found in pipeline "${pipeline}".`);
  }

  const jobNames = jobs.map(j => j.name);

  // Try each pattern in priority order
  for (const pattern of PR_JOB_PATTERNS) {
    const match = jobNames.find(name => pattern.test(name));
    if (match) return match;
  }

  throw new Error(
    `Could not auto-detect PR job in pipeline "${pipeline}". ` +
    `Available jobs: [${jobNames.join(', ')}]. ` +
    `Specify the job explicitly with the "job" parameter.`
  );
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function execute(input: Input) {
  if (!input.pipeline) {
    throw new Error('pipeline is required');
  }

  // Auto-detect job if not provided
  const job = input.job || detectPrJob(input.pipeline);

  const timeoutSeconds = input.timeout_seconds ?? 600;
  const pollInterval = input.poll_interval ?? 30;
  const startTime = Date.now();
  const deadline = startTime + timeoutSeconds * 1000;

  let lastStatus = '';
  let pollCount = 0;

  while (Date.now() < deadline) {
    pollCount++;
    const builds = flyExecJson<Build[]>(['builds', '-j', `${input.pipeline}/${job}`, '--count', '5']);

    if (!Array.isArray(builds) || builds.length === 0) {
      // No builds yet — wait and retry
      if (Date.now() + pollInterval * 1000 > deadline) break;
      await sleep(pollInterval * 1000);
      continue;
    }

    // Find the target build
    let build: Build | undefined;
    if (input.build_name) {
      build = builds.find(b => b.name === input.build_name);
      if (!build) {
        throw new Error(`Build #${input.build_name} not found in ${input.pipeline}/${input.job}`);
      }
    } else {
      // Latest build (first in list, sorted by recency)
      build = builds[0];
    }

    lastStatus = build.status;

    // Terminal states
    if (['succeeded', 'failed', 'errored', 'aborted'].includes(build.status)) {
      const elapsed = Math.round((Date.now() - startTime) / 1000);
      return {
        target: getFlyTarget(),
        pipeline: input.pipeline,
        job,
        build_id: build.id,
        build_name: build.name,
        status: build.status,
        passed: build.status === 'succeeded',
        elapsed_seconds: elapsed,
        poll_count: pollCount,
        start_time: build.start_time,
        end_time: build.end_time,
      };
    }

    // Still running — wait and poll again
    if (Date.now() + pollInterval * 1000 > deadline) break;
    await sleep(pollInterval * 1000);
  }

  // Timed out
  const elapsed = Math.round((Date.now() - startTime) / 1000);
  return {
    target: getFlyTarget(),
    pipeline: input.pipeline,
    job: input.job,
    status: lastStatus || 'unknown',
    passed: false,
    timed_out: true,
    elapsed_seconds: elapsed,
    poll_count: pollCount,
    timeout_seconds: timeoutSeconds,
  };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

#!/usr/bin/env npx tsx
// pipeline_health - Get deploy/validate job health for all production Concourse pipelines.
// Returns structured JSON — no per-job API calls needed, finished_build is embedded in list_jobs response.
import { concourseRequest, getConcourseCredentials } from './concourse-client.js';

// Production pipeline registry
//   prod: deploys to production — scored in Gates 1 and 5 of release-ready
//   e2e:  end-to-end test suite  — scored in Gate 4 of release-ready
const PIPELINES: { name: string; role: 'prod' | 'e2e' }[] = [
  { name: 'lambda-functions',   role: 'prod' },
  { name: 'frontend-app',         role: 'prod' },
  { name: 'auth-service',        role: 'prod' },
  { name: 'core-infra',        role: 'prod' },
  { name: 'migrations',  role: 'prod' },
  { name: 'publisher-sdk', role: 'prod' },
  { name: 'mcp-server',  role: 'prod' },
  { name: 'dashboard',   role: 'prod' },
  { name: 'bootstrap',   role: 'prod' },
  { name: 'query-proxy', role: 'prod' },
  { name: 'go-common',   role: 'prod' },
  { name: 'e2e-tests',         role: 'e2e'  },
];

// Job name patterns for classification.
// deploy: counts toward production health scoring
// pr_gate: advisory only unless a cross-repo blocker
// other: ignored for scoring
const DEPLOY_PATTERN = /^(deploy|validate|terraform-apply|promote-to|publish|build|apply|release)/;
const PR_GATE_PATTERN = /^pr-/;

interface ConcourseBuild {
  id: number;
  name: string;        // build number as string, e.g. "287"
  status: string;      // succeeded | failed | errored | aborted | started | pending
  start_time?: number; // Unix timestamp
  end_time?: number;   // Unix timestamp
  team_name: string;
  pipeline_name: string;
  job_name: string;
}

interface ConcourseJob {
  id: number;
  name: string;
  team_name: string;
  pipeline_name: string;
  paused?: boolean;
  finished_build?: ConcourseBuild; // most recently completed build
  next_build?: ConcourseBuild;     // currently running build (if any)
}

interface ConcoursePipeline {
  id: number;
  name: string;
  paused: boolean;
  team_name: string;
}

export interface JobHealth {
  name: string;
  type: 'deploy' | 'pr_gate' | 'other';
  status: string; // succeeded | failed | errored | aborted | started | pending | no_build
  started_at: number | null;
  finished_at: number | null;
  url: string | null;
}

export interface PipelineHealth {
  pipeline: string;
  role: 'prod' | 'e2e';
  paused: boolean;
  deploy_jobs: JobHealth[];
  pr_gate_jobs: JobHealth[];
  in_flight_count: number;
  error?: string; // set if the pipeline was not found or the API call failed
}

function classifyJob(name: string): 'deploy' | 'pr_gate' | 'other' {
  if (DEPLOY_PATTERN.test(name)) return 'deploy';
  if (PR_GATE_PATTERN.test(name)) return 'pr_gate';
  return 'other';
}

function mapJob(job: ConcourseJob, baseUrl: string): JobHealth {
  // Prefer next_build if it's currently running, otherwise use finished_build
  const build = job.next_build?.status === 'started' ? job.next_build : job.finished_build;
  const url = build
    ? `${baseUrl}/teams/${job.team_name}/pipelines/${encodeURIComponent(job.pipeline_name)}/jobs/${encodeURIComponent(job.name)}/builds/${build.name}`
    : null;
  return {
    name: job.name,
    type: classifyJob(job.name),
    status: build?.status ?? 'no_build',
    started_at: build?.start_time ?? null,
    finished_at: build?.end_time ?? null,
    url,
  };
}

async function fetchPipelineHealth(
  pipelineName: string,
  role: 'prod' | 'e2e',
  paused: boolean,
  baseUrl: string,
  team: string,
): Promise<PipelineHealth> {
  try {
    const jobs = await concourseRequest<ConcourseJob[]>(
      'GET',
      `/api/v1/teams/${team}/pipelines/${encodeURIComponent(pipelineName)}/jobs`,
    );
    const mapped = jobs.map(j => mapJob(j, baseUrl));
    return {
      pipeline: pipelineName,
      role,
      paused,
      deploy_jobs: mapped.filter(j => j.type === 'deploy'),
      pr_gate_jobs: mapped.filter(j => j.type === 'pr_gate'),
      in_flight_count: mapped.filter(j => j.status === 'started').length,
    };
  } catch (err) {
    return {
      pipeline: pipelineName,
      role,
      paused,
      deploy_jobs: [],
      pr_gate_jobs: [],
      in_flight_count: 0,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

async function execute(): Promise<PipelineHealth[]> {
  const creds = getConcourseCredentials();
  const { url: baseUrl, team } = creds;

  // Get all pipelines in one call to check paused status, then fetch jobs in parallel
  const allPipelines = await concourseRequest<ConcoursePipeline[]>(
    'GET',
    `/api/v1/teams/${team}/pipelines`,
  );
  const pausedMap = new Map(allPipelines.map(p => [p.name, p.paused]));

  return Promise.all(
    PIPELINES.map(({ name, role }) =>
      fetchPipelineHealth(name, role, pausedMap.get(name) ?? false, baseUrl, team)
    )
  );
}

execute()
  .then(r => console.log(JSON.stringify(r, null, 2)))
  .catch(e => { console.error(e.message); process.exit(1); });

#!/usr/bin/env npx tsx
// list_builds - List builds for a job in a pipeline.
import { concourseRequest, getTeam } from './concourse-client.js';

interface Input {
  pipeline_name: string;
  job_name: string;
  limit?: number;
}

async function execute(input: Input) {
  const team = getTeam();
  const params = new URLSearchParams();
  if (input.limit) params.append('limit', String(input.limit));
  const query = params.toString() ? `?${params.toString()}` : '';

  return concourseRequest(
    'GET',
    `/api/v1/teams/${team}/pipelines/${encodeURIComponent(input.pipeline_name)}/jobs/${encodeURIComponent(input.job_name)}/builds${query}`
  );
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

#!/usr/bin/env npx tsx
// set_pipeline - Set or update a pipeline configuration.
import { concourseRequest, getTeam } from './concourse-client.js';

interface Input {
  pipeline_name: string;
  config: Record<string, unknown>;
}

async function execute(input: Input) {
  const team = getTeam();
  return concourseRequest(
    'PUT',
    `/api/v1/teams/${team}/pipelines/${encodeURIComponent(input.pipeline_name)}/config`,
    input.config
  );
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

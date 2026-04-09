#!/usr/bin/env npx tsx
// unpause_pipeline - Unpause a pipeline to resume scheduling builds.
import { concourseRequest, getTeam } from './concourse-client.js';

interface Input {
  pipeline_name: string;
}

async function execute(input: Input) {
  const team = getTeam();
  return concourseRequest('PUT', `/api/v1/teams/${team}/pipelines/${encodeURIComponent(input.pipeline_name)}/unpause`);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

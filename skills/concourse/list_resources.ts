#!/usr/bin/env npx tsx
// list_resources - List all resources for a pipeline.
import { concourseRequest, getTeam } from './concourse-client.js';

interface Input {
  pipeline_name: string;
}

async function execute(input: Input) {
  const team = getTeam();
  return concourseRequest('GET', `/api/v1/teams/${team}/pipelines/${encodeURIComponent(input.pipeline_name)}/resources`);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

#!/usr/bin/env npx tsx
// list_pipelines - List all pipelines for the team.
import { concourseRequest, getTeam } from './concourse-client.js';

interface Input {}

async function execute(_input: Input) {
  const team = getTeam();
  return concourseRequest('GET', `/api/v1/teams/${team}/pipelines`);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

#!/usr/bin/env npx tsx
// get_build - Get detailed information about a specific build.
import { concourseRequest } from './concourse-client.js';

interface Input {
  build_id: number;
}

async function execute(input: Input) {
  return concourseRequest('GET', `/api/v1/builds/${input.build_id}`);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

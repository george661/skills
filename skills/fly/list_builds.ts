#!/usr/bin/env npx tsx
// list_builds - List recent builds on the Concourse target with optional filtering.
import { flyExecJson, getFlyTarget } from './fly-client.js';

interface Input {
  count?: number;
  pipeline?: string;
  job?: string;
}

async function execute(input: Input) {
  const args = ['builds'];
  const count = input.count ?? 25;
  args.push('--count', String(count));

  if (input.pipeline) {
    if (input.job) {
      args.push('-j', `${input.pipeline}/${input.job}`);
    } else {
      args.push('-p', input.pipeline);
    }
  }

  const builds = flyExecJson<unknown[]>(args);
  return {
    target: getFlyTarget(),
    count: Array.isArray(builds) ? builds.length : 0,
    filters: {
      pipeline: input.pipeline ?? null,
      job: input.job ?? null,
      requested_count: count,
    },
    builds,
  };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

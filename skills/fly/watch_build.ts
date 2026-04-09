#!/usr/bin/env npx tsx
// watch_build - Watch or retrieve the output of a specific Concourse build.
import { flyExec, getFlyTarget } from './fly-client.js';

interface Input {
  build_id: number;
}

async function execute(input: Input) {
  if (input.build_id === undefined || input.build_id === null) {
    throw new Error('build_id is required');
  }

  const output = flyExec(['watch', '-b', String(input.build_id)]);
  return {
    target: getFlyTarget(),
    build_id: input.build_id,
    output,
  };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

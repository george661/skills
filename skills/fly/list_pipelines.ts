#!/usr/bin/env npx tsx
// list_pipelines - List all pipelines on the Concourse target.
import { flyExecJson, getFlyTarget } from './fly-client.js';

interface Input {}

async function execute(_input: Input) {
  const pipelines = flyExecJson<unknown[]>(['pipelines']);
  return {
    target: getFlyTarget(),
    count: Array.isArray(pipelines) ? pipelines.length : 0,
    pipelines,
  };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

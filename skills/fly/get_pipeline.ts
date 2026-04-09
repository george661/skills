#!/usr/bin/env npx tsx
// get_pipeline - Get the configuration of a Concourse pipeline as JSON.
import { flyExecJson, getFlyTarget } from './fly-client.js';

interface Input {
  pipeline_name: string;
}

async function execute(input: Input) {
  if (!input.pipeline_name) {
    throw new Error('pipeline_name is required');
  }

  const config = flyExecJson<Record<string, unknown>>(['get-pipeline', '-p', input.pipeline_name]);
  return {
    target: getFlyTarget(),
    pipeline_name: input.pipeline_name,
    config,
  };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

#!/usr/bin/env npx tsx
// set_pipeline - Set (create or update) a Concourse pipeline from a YAML configuration file.
import { flyExec, getFlyTarget } from './fly-client.js';

interface Input {
  pipeline_name: string;
  pipeline_file: string;
  vars?: Record<string, string>;
}

async function execute(input: Input) {
  if (!input.pipeline_name) {
    throw new Error('pipeline_name is required');
  }
  if (!input.pipeline_file) {
    throw new Error('pipeline_file is required');
  }

  const args = ['set-pipeline', '-p', input.pipeline_name, '-c', input.pipeline_file, '--non-interactive'];

  if (input.vars) {
    for (const [key, value] of Object.entries(input.vars)) {
      args.push('--var', `${key}=${value}`);
    }
  }

  const output = flyExec(args);
  return {
    success: true,
    target: getFlyTarget(),
    pipeline_name: input.pipeline_name,
    pipeline_file: input.pipeline_file,
    message: output,
  };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

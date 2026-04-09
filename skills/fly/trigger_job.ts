#!/usr/bin/env npx tsx
// trigger_job - Trigger a job in a Concourse pipeline.
import { flyExec, getFlyTarget } from './fly-client.js';

interface Input {
  pipeline_name: string;
  job_name: string;
  watch?: boolean;
}

async function execute(input: Input) {
  if (!input.pipeline_name) {
    throw new Error('pipeline_name is required');
  }
  if (!input.job_name) {
    throw new Error('job_name is required');
  }

  const jobRef = `${input.pipeline_name}/${input.job_name}`;
  const args = ['trigger-job', '-j', jobRef];

  if (input.watch) {
    args.push('--watch');
  }

  const output = flyExec(args);
  return {
    success: true,
    target: getFlyTarget(),
    pipeline_name: input.pipeline_name,
    job_name: input.job_name,
    watched: input.watch ?? false,
    output,
  };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

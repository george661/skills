#!/usr/bin/env npx tsx
// abort_build - Cancel a running Concourse build.
import { flyExec, getFlyTarget } from './fly-client.js';

interface Input {
  build_id?: number;
  job?: string;
  build_number?: number;
}

async function execute(input: Input) {
  if (input.build_id && (input.job || input.build_number)) {
    throw new Error('Provide either build_id OR job+build_number, not both');
  }
  if (!input.build_id && !(input.job && input.build_number)) {
    throw new Error('Either build_id or both job and build_number must be provided');
  }

  const args = ['abort-build'];
  if (input.job) {
    args.push('-j', input.job, '-b', String(input.build_number));
  } else {
    args.push('-b', String(input.build_id));
  }

  const output = flyExec(args);
  return {
    success: true,
    target: getFlyTarget(),
    message: output || `build ${input.build_id || `${input.job}#${input.build_number}`} was aborted`,
  };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

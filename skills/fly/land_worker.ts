#!/usr/bin/env npx tsx
// land_worker - Gracefully drain a worker for temporary maintenance.
import { flyExec, getFlyTarget } from './fly-client.js';

interface Input {
  worker: string;
}

async function execute(input: Input) {
  if (!input.worker) {
    throw new Error('worker is required');
  }

  const output = flyExec(['land-worker', '-w', input.worker]);
  return {
    success: true,
    target: getFlyTarget(),
    worker: input.worker,
    message: output || `landing worker ${input.worker}`,
  };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

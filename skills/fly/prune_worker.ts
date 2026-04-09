#!/usr/bin/env npx tsx
// prune_worker - Remove a stalled worker from the Concourse database.
import { flyExec, getFlyTarget } from './fly-client.js';

interface Input {
  worker?: string;
  all_stalled?: boolean;
}

async function execute(input: Input) {
  if (!input.worker && !input.all_stalled) {
    throw new Error('Either worker or all_stalled must be provided');
  }

  const args = ['prune-worker'];
  if (input.all_stalled) {
    args.push('--all-stalled');
  } else if (input.worker) {
    args.push('-w', input.worker);
  }

  const output = flyExec(args);
  return {
    success: true,
    target: getFlyTarget(),
    worker: input.worker || 'all-stalled',
    message: output || `pruned worker ${input.worker || '(all stalled)'}`,
  };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

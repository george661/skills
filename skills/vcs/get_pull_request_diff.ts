#!/usr/bin/env npx tsx
// get_pull_request_diff — unified VCS wrapper. Delegates to github-mcp or bitbucket.
import { resolve, delegate } from './vcs-router.js';

interface Input {
  [key: string]: unknown;
  repo: string;
  pr_number: number;
  provider?: string;
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
const ctx = resolve(input.repo, input.provider);
delegate(ctx, 'get_pull_request_diff', input)
  .then((r) => console.log(typeof r === 'string' ? r : String(r)))
  .catch((e) => { console.error(e.message); process.exit(1); });

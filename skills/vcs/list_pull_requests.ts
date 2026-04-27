#!/usr/bin/env npx tsx
// list_pull_requests - List pull requests from a repository (delegates to VCS provider).
import { resolve, delegate } from './vcs-router.js';

interface Input {
  repo: string;
  state?: 'open' | 'closed' | 'all';
  provider?: string;
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
const ctx = resolve(input.repo, input.provider);
delegate(ctx, 'list_pull_requests', input)
  .then((r) => console.log(typeof r === 'string' ? r : JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

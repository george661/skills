#!/usr/bin/env npx tsx
// create_pull_request — unified VCS wrapper. Delegates to github-mcp or bitbucket.
import { resolve, delegate } from './vcs-router.js';

interface Input {
  [key: string]: unknown;
  repo: string;
  title: string;
  source_branch: string;
  target_branch?: string;
  description?: string;
  provider?: string;
  reviewers?: string[];
  close_source_branch?: boolean;
  draft?: boolean;
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
const ctx = resolve(input.repo, input.provider);
delegate(ctx, 'create_pull_request', input)
  .then((r) => console.log(typeof r === 'string' ? r : JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

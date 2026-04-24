#!/usr/bin/env npx tsx
// merge_pull_request — unified VCS wrapper. Delegates to github-mcp or bitbucket.
import { resolve, delegate } from './vcs-router.js';

interface Input {
  [key: string]: unknown;
  repo: string;
  pr_number: number;
  provider?: string;
  message?: string;
  commit_title?: string;
  commit_message?: string;
  strategy?: string;
  merge_method?: string;
  close_source_branch?: boolean;
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
const ctx = resolve(input.repo, input.provider);

// Normalize merge strategy param
if (ctx.provider === 'github' && input.strategy && !input.merge_method) {
  const strategyMap: Record<string, string> = {
    merge_commit: 'merge', squash: 'squash', fast_forward: 'rebase',
  };
  (input as any).merge_method = strategyMap[input.strategy] || input.strategy;
  delete (input as any).strategy;
}

delegate(ctx, 'merge_pull_request', input)
  .then((r) => console.log(typeof r === 'string' ? r : JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

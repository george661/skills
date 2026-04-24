#!/usr/bin/env npx tsx
// add_pull_request_comment — unified VCS wrapper. Delegates to github-mcp or bitbucket.
import { resolve, delegate } from './vcs-router.js';

interface Input {
  [key: string]: unknown;
  repo: string;
  pr_number: number;
  comment_text: string;
  provider?: string;
  path?: string;
  line?: number;
  parent_id?: number;
  commit_id?: string;
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
const ctx = resolve(input.repo, input.provider);

// Route inline vs general comments for GitHub
if (ctx.provider === 'github' && input.path && input.line) {
  // Inline review comment needs commit_id on GitHub
  delegate(ctx, 'create_pull_request_review_comment', {
    repo: input.repo,
    pr_number: input.pr_number,
    comment_text: input.comment_text,
    path: input.path,
    line: input.line,
    commit_id: input.commit_id || '',
  })
    .then((r) => console.log(typeof r === 'string' ? r : JSON.stringify(r, null, 2)))
    .catch((e) => { console.error(e.message); process.exit(1); });
} else {
  delegate(ctx, 'add_pull_request_comment', input)
    .then((r) => console.log(typeof r === 'string' ? r : JSON.stringify(r, null, 2)))
    .catch((e) => { console.error(e.message); process.exit(1); });
}

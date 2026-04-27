#!/usr/bin/env npx tsx
// add_issue_link - Create a cross-reference between two GitHub issues via comments.
// GitHub doesn't have a native "link" API outside of Projects v2, so we post mutual comments.
import { githubRequest } from './github-client.js';

interface Input {
  from_issue: string;  // format: owner/repo#123
  to_issue: string;    // format: owner/repo#456
  comment?: string;    // optional context
}

interface Result {
  success: boolean;
  from_comment: { id: number; html_url: string };
  to_comment: { id: number; html_url: string };
}

async function execute(params: Input): Promise<Result> {
  // Parse from_issue
  const fromMatch = params.from_issue.match(/^([^/]+)\/([^#]+)#(\d+)$/);
  if (!fromMatch) {
    throw new Error(`Invalid from_issue format: "${params.from_issue}". Expected: owner/repo#123`);
  }
  const [, fromOwner, fromRepo, fromNumber] = fromMatch;

  // Parse to_issue
  const toMatch = params.to_issue.match(/^([^/]+)\/([^#]+)#(\d+)$/);
  if (!toMatch) {
    throw new Error(`Invalid to_issue format: "${params.to_issue}". Expected: owner/repo#456`);
  }
  const [, toOwner, toRepo, toNumber] = toMatch;

  const context = params.comment ? `\n\n${params.comment}` : '';

  // Post comment on from_issue referencing to_issue
  const fromCommentBody = `Related to ${toOwner}/${toRepo}#${toNumber}${context}`;
  const fromComment = await githubRequest<{ id: number; html_url: string }>(
    `/repos/${fromOwner}/${fromRepo}/issues/${fromNumber}/comments`,
    'POST',
    { body: fromCommentBody }
  );

  // Post comment on to_issue referencing from_issue
  const toCommentBody = `Related to ${fromOwner}/${fromRepo}#${fromNumber}${context}`;
  const toComment = await githubRequest<{ id: number; html_url: string }>(
    `/repos/${toOwner}/${toRepo}/issues/${toNumber}/comments`,
    'POST',
    { body: toCommentBody }
  );

  return {
    success: true,
    from_comment: fromComment,
    to_comment: toComment,
  };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

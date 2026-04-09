#!/usr/bin/env npx tsx
// search_issues - Search for GitHub issues. Accepts a `jql` param for Jira-like queries
// or a raw `query` param for native GitHub search syntax.
import { githubRequest, getGitHubCredentials } from './github-client.js';

interface Input {
  owner?: string;
  repo?: string;
  query?: string;
  jql?: string;
  per_page?: number;
  page?: number;
}

/**
 * Translate simple Jira-like query conventions to GitHub search syntax.
 * Examples:
 *   "project = my-repo AND status = open" → "repo:owner/my-repo is:open"
 *   "assignee = octocat" → "assignee:octocat"
 */
function translateJql(jql: string, defaultOwner: string): string {
  let q = jql;

  // project = REPO → repo:owner/repo
  q = q.replace(/project\s*=\s*["']?(\S+?)["']?(\s|$)/gi, (_, repo, ws) =>
    `repo:${defaultOwner}/${repo}${ws}`);

  // status = open|closed → is:open|closed
  q = q.replace(/status\s*=\s*["']?(open|closed)["']?/gi, (_, state) =>
    `is:${state.toLowerCase()}`);

  // assignee = name → assignee:name
  q = q.replace(/assignee\s*=\s*["']?(\S+?)["']?(\s|$)/gi, (_, name, ws) =>
    `assignee:${name}${ws}`);

  // label = name → label:name
  q = q.replace(/label\s*=\s*["']?(\S+?)["']?(\s|$)/gi, (_, name, ws) =>
    `label:${name}${ws}`);

  // Strip remaining AND/OR connectors
  q = q.replace(/\b(AND|OR)\b/gi, '').replace(/\s+/g, ' ').trim();

  return q;
}

async function execute(input: Input) {
  const { defaultOwner } = getGitHubCredentials();
  const owner = input.owner || defaultOwner;

  let q: string;
  if (input.jql) {
    q = translateJql(input.jql, owner);
  } else if (input.query) {
    q = input.query;
  } else {
    // Default: list issues in repo
    q = `repo:${owner}/${input.repo || ''} is:issue`;
  }

  // Ensure is:issue is present so we exclude PRs
  if (!q.includes('is:issue') && !q.includes('is:pr')) {
    q += ' is:issue';
  }

  const params = new URLSearchParams({
    q,
    per_page: String(input.per_page || 30),
    page: String(input.page || 1),
  });

  return githubRequest('GET', `/search/issues?${params}`);
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

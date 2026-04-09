#!/usr/bin/env npx tsx
// update_issue — unified issue tracker wrapper. Delegates to jira, github-issues, or linear.
import { resolveIssueProvider, delegateIssue } from './issues-router.js';

interface Input { [k: string]: unknown; issue_key: string; summary?: string; description?: string; labels?: string[]; priority?: string; provider?: string; }

const input = JSON.parse(process.argv[2] || '{}') as Input;
const provider = resolveIssueProvider(input.provider);
try {
  const r = delegateIssue(provider, 'update_issue', input);
  console.log(typeof r === 'string' ? r : JSON.stringify(r, null, 2));
} catch (e: any) { console.error(e.message); process.exit(1); }

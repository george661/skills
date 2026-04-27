#!/usr/bin/env npx tsx
// list_pull_requests - List pull requests from a repository (delegates to VCS provider).
import { resolveVCSProvider, delegateVCS } from './vcs-router.js';

interface Input {
  repo: string;
  state?: 'open' | 'closed' | 'all';
  provider?: string;
}

const params = JSON.parse(process.argv[2] || '{}') as Input;
const provider = resolveVCSProvider(params.provider, params.repo);
const result = delegateVCS(provider, 'list_pull_requests', params);

console.log(JSON.stringify(result, null, 2));

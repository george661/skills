#!/usr/bin/env npx tsx
// list_builds — unified CI wrapper. Delegates to concourse, github-actions, or circleci.
import { resolveCIProvider, delegateCI } from './ci-router.js';

interface Input { [k: string]: unknown; repo: string; branch?: string; status?: string; provider?: string; }

const input = JSON.parse(process.argv[2] || '{}') as Input;
const provider = resolveCIProvider(input.provider);
try {
  const r = delegateCI(provider, 'list_builds', input);
  console.log(typeof r === 'string' ? r : JSON.stringify(r, null, 2));
} catch (e: any) { console.error(e.message); process.exit(1); }

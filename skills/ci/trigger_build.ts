#!/usr/bin/env npx tsx
// trigger_build — unified CI wrapper. Delegates to concourse, github-actions, or circleci.
import { resolveCIProvider, delegateCI } from './ci-router.js';

interface Input { [k: string]: unknown; repo: string; job?: string; workflow_id?: string; ref?: string; provider?: string; }

const input = JSON.parse(process.argv[2] || '{}') as Input;
const provider = resolveCIProvider(input.provider);
try {
  const r = delegateCI(provider, 'trigger_build', input);
  console.log(typeof r === 'string' ? r : JSON.stringify(r, null, 2));
} catch (e: any) { console.error(e.message); process.exit(1); }

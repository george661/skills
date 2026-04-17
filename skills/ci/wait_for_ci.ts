#!/usr/bin/env npx tsx
/**
 * wait_for_ci.ts — Unified CI wait wrapper that resolves provider and delegates.
 *
 * Unlike other ci/ skills, this bypasses delegateCI() because wait operations
 * can run for up to 900s, exceeding the 60s spawnSync timeout in ci-router.
 * Instead, we use the router helpers (resolveCIProvider, translateParams) and
 * spawn the backend skill directly with the full timeout.
 *
 * Usage:
 *   npx tsx wait_for_ci.ts '{"repo": "gw-spa", "timeout_seconds": 900}'
 *   npx tsx wait_for_ci.ts '{"repo": "gw-spa", "provider": "github_actions"}'
 *
 * Returns:
 *   {
 *     "run": "<build-url>",
 *     "success": true,
 *     "build_id": 1234,
 *     "status": "succeeded",
 *     "output": {
 *       "build": { "success": true, "logs": ["line1", "line2"] },
 *       "test":  { "success": false, "logs": ["FAIL: TestFoo"] }
 *     }
 *   }
 */
import { spawn } from 'child_process';
import { existsSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';
import { resolveCIProvider, translateParams } from './ci-router.js';
import type { CIProvider } from './ci-router.js';

const DEBUG = !!process.env.CI_DEBUG;

function debug(...args: unknown[]) {
  if (DEBUG) process.stderr.write(`[ci/wait_for_ci] ${args.map(String).join(' ')}\n`);
}

interface Input {
  repo?: string;
  pipeline?: string;
  job?: string;
  url?: string;
  build?: string | number;
  timeout_seconds?: number;
  poll_interval?: number;
  provider?: string;
}

interface TaskOutput {
  success: boolean;
  logs: string[];
}

interface BuildResult {
  run: string;
  success: boolean;
  build_id: number;
  status: string;
  output: Record<string, TaskOutput>;
}

const SKILL_MAP: Record<CIProvider, { dir: string; name: string }> = {
  concourse: { dir: 'fly', name: 'wait-for-ci' },
  github_actions: { dir: 'github-actions', name: 'wait_for_workflow_run' },
  circleci: { dir: 'circleci', name: 'wait_for_build' },
};

async function execute(input: Input): Promise<BuildResult> {
  // 1. Resolve provider
  const provider = resolveCIProvider(input.provider);
  debug('resolved provider:', provider);

  // 2. Resolve backend skill path
  const mapping = SKILL_MAP[provider];
  if (!mapping) {
    throw new Error(`Unsupported CI provider: ${provider}`);
  }

  const skillPath = join(homedir(), '.claude', 'skills', mapping.dir, `${mapping.name}.ts`);
  if (!existsSync(skillPath)) {
    throw new Error(`CI skill not found: ${skillPath} (provider: ${provider})`);
  }
  debug('backend skill:', skillPath);

  // 3. Translate params (repo → pipeline for Concourse)
  const translatedParams = translateParams(provider, 'wait_for_ci', input);
  debug('translated params:', JSON.stringify(translatedParams));

  // 4. Spawn backend skill with full timeout (not limited to 60s)
  const timeoutMs = (input.timeout_seconds ?? 900) * 1000 + 10000; // backend timeout + 10s buffer

  return new Promise<BuildResult>((resolve, reject) => {
    let stdout = '';
    let stderr = '';

    const child = spawn('npx', ['tsx', skillPath, JSON.stringify(translatedParams)], {
      stdio: ['pipe', 'pipe', 'pipe'],
      timeout: timeoutMs,
    });

    child.stdout.on('data', (data) => {
      stdout += data.toString();
    });

    child.stderr.on('data', (data) => {
      stderr += data.toString();
    });

    child.on('error', (err) => {
      reject(new Error(`Failed to spawn backend skill: ${err.message}`));
    });

    child.on('close', (code) => {
      if (code !== 0) {
        const errMsg = stderr.trim() || `Backend skill exited with code ${code}`;
        reject(new Error(errMsg));
        return;
      }

      try {
        const result = JSON.parse(stdout) as BuildResult;
        resolve(result);
      } catch (err) {
        reject(new Error(`Failed to parse backend skill output: ${err instanceof Error ? err.message : String(err)}`));
      }
    });
  });
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then(r => console.log(JSON.stringify(r, null, 2)))
  .catch(e => { console.error(e.message); process.exit(1); });

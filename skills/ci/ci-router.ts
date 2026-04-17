#!/usr/bin/env npx tsx
/**
 * CI Router — resolves CI/CD provider (concourse/github_actions/circleci) and
 * delegates to the right backend skill.
 *
 * Provider resolution order:
 * 1. Explicit `provider` argument
 * 2. CI_PROVIDER environment variable
 * 3. Default: concourse
 *
 * Usage from other ci/ skills:
 *   import { resolveCIProvider, translateParams, delegateCI } from './ci-router.js';
 *   const provider = resolveCIProvider();
 *   const result = delegateCI(provider, 'get_build_status', { repo: 'my-api' });
 */
import { spawnSync } from 'child_process';
import { existsSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';

// ---------------------------------------------------------------------------
// Debug
// ---------------------------------------------------------------------------

const DEBUG = !!process.env.CI_DEBUG;

function debug(...args: unknown[]) {
  if (DEBUG) process.stderr.write(`[ci-router] ${args.map(String).join(' ')}\n`);
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type CIProvider = 'concourse' | 'github_actions' | 'circleci';

// ---------------------------------------------------------------------------
// Skill name mapping — unified name → provider-specific skill path
//
// Concourse delegates to either skills/concourse/ or skills/fly/ depending
// on the operation. GitHub Actions delegates to skills/github-actions/.
// ---------------------------------------------------------------------------

interface SkillMapping {
  dir: string;   // skill directory name under ~/.claude/skills/
  name: string;  // skill file name (without .ts)
}

const SKILL_MAP: Record<string, Partial<Record<CIProvider, SkillMapping>>> = {
  get_build_status: {
    concourse:      { dir: 'concourse', name: 'get_build' },
    github_actions: { dir: 'github-actions', name: 'get_workflow_run' },
  },
  trigger_build: {
    concourse:      { dir: 'fly', name: 'trigger_job' },
    github_actions: { dir: 'github-actions', name: 'trigger_workflow' },
  },
  get_build_logs: {
    concourse:      { dir: 'fly', name: 'watch_build' },
    github_actions: { dir: 'github-actions', name: 'get_run_logs' },
  },
  list_builds: {
    concourse:      { dir: 'concourse', name: 'list_builds' },
    github_actions: { dir: 'github-actions', name: 'list_workflow_runs' },
  },
  wait_for_ci: {
    concourse:      { dir: 'fly', name: 'wait-for-ci' },
    github_actions: { dir: 'github-actions', name: 'wait_for_workflow_run' },
  },
};

// Export wait_for_ci mapping for use by skills/ci/wait_for_ci.ts
export const WAIT_FOR_CI_SKILL_MAP: Partial<Record<CIProvider, SkillMapping>> = SKILL_MAP.wait_for_ci;

// ---------------------------------------------------------------------------
// Provider → default skill directory mapping (fallback for unmapped skills)
// ---------------------------------------------------------------------------

const PROVIDER_DEFAULT_DIR: Record<CIProvider, string> = {
  concourse: 'concourse',
  github_actions: 'github-actions',
  circleci: 'circleci',
};

// ---------------------------------------------------------------------------
// resolveCIProvider
// ---------------------------------------------------------------------------

/**
 * Resolve which CI provider to use.
 *
 * 1. Explicit argument (highest priority)
 * 2. CI_PROVIDER env var
 * 3. Default: concourse
 */
export function resolveCIProvider(explicit?: string): CIProvider {
  debug('resolveCIProvider called, explicit:', explicit);

  // 1. Explicit override
  if (explicit && isValidProvider(explicit)) {
    debug('resolved via explicit arg:', explicit);
    return explicit;
  }

  // 2. Environment variable
  const envVal = process.env.CI_PROVIDER;
  if (envVal && isValidProvider(envVal)) {
    debug('resolved via CI_PROVIDER env:', envVal);
    return envVal;
  }

  // 3. Default
  debug('resolved via default: concourse');
  return 'concourse';
}

function isValidProvider(value: string): value is CIProvider {
  return value === 'concourse' || value === 'github_actions' || value === 'circleci';
}

// ---------------------------------------------------------------------------
// translateParams
// ---------------------------------------------------------------------------

/**
 * Translate unified CI params to provider-specific params.
 *
 * - Concourse: `repo` → `pipeline`, passthrough others
 * - GitHub Actions: inject `owner` from GITHUB_OWNER env, `run_id` passthrough
 */
export function translateParams(
  provider: CIProvider,
  skill: string,
  params: Record<string, unknown>,
): Record<string, unknown> {
  debug('translateParams:', provider, skill, JSON.stringify(params));

  if (provider === 'concourse') {
    return translateConcourseParams(skill, params);
  }

  if (provider === 'github_actions') {
    return translateGitHubActionsParams(skill, params);
  }

  // Fallback passthrough for circleci / unknown
  return { ...params };
}

function translateConcourseParams(
  _skill: string,
  params: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...params };

  // Unified `repo` → Concourse `pipeline`
  if ('repo' in out) {
    out.pipeline = out.repo;
    delete out.repo;
  }

  // Clean provider field
  delete out.provider;

  return out;
}

function translateGitHubActionsParams(
  _skill: string,
  params: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...params };

  // Inject owner from env if not explicitly provided
  if (!out.owner && process.env.GITHUB_OWNER) {
    out.owner = process.env.GITHUB_OWNER;
  }

  // run_id passthrough (already in correct format)

  // Clean provider field
  delete out.provider;

  return out;
}

// ---------------------------------------------------------------------------
// delegateCI
// ---------------------------------------------------------------------------

/**
 * Delegate to the appropriate provider skill.
 *
 * Resolves the skill directory and file, translates params,
 * then spawns the provider skill via `npx tsx`.
 */
export function delegateCI(
  provider: CIProvider,
  skill: string,
  params: Record<string, unknown>,
): unknown {
  // Resolve provider-specific skill mapping
  const mapping = SKILL_MAP[skill]?.[provider];
  const skillDir = mapping?.dir ?? PROVIDER_DEFAULT_DIR[provider];
  const skillName = mapping?.name ?? skill;

  const translatedParams = translateParams(provider, skillName, params);

  // Resolve skill path
  const skillBase = join(homedir(), '.claude', 'skills', skillDir);
  const skillPath = join(skillBase, `${skillName}.ts`);

  if (!existsSync(skillPath)) {
    throw new Error(
      `CI skill not found: ${skillPath} (provider: ${provider}, skill: ${skill} → ${skillName})`,
    );
  }

  debug('delegateCI:', provider, skill, '->', skillPath);
  debug('params:', JSON.stringify(translatedParams));

  // Use spawnSync to avoid shell escaping issues with JSON containing quotes
  const child = spawnSync('npx', ['tsx', skillPath, JSON.stringify(translatedParams)], {
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe'],
    timeout: 60000,
  });

  if (child.error) throw child.error;
  if (child.status !== 0) {
    const stderr = child.stderr?.trim() || '';
    throw new Error(stderr || `CI skill '${skillName}' exited with code ${child.status}`);
  }

  const result = child.stdout;
  try {
    return JSON.parse(result);
  } catch {
    return result; // plain text fallback
  }
}

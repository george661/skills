#!/usr/bin/env npx tsx
/**
 * VCS Router — resolves provider (github/bitbucket) and delegates to the right backend skill.
 *
 * Provider resolution order:
 * 1. Explicit `provider` field in input
 * 2. ~/.claude/config/repo-vcs.json lookup by repo name
 * 3. Git remote URL detection at $WORKSPACE_ROOT/<repo>/
 * 4. Default: bitbucket
 *
 * Usage from other vcs/ skills:
 *   import { resolve, delegate } from './vcs-router.js';
 *   const ctx = resolve(input.repo);
 *   const result = await delegate(ctx, 'get_pull_request', { pr_number: 42 });
 */
import { execSync, spawnSync } from 'child_process';
import { readFileSync, existsSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';

const DEBUG = !!process.env.VCS_DEBUG;
function debug(...args: unknown[]) {
  if (DEBUG) process.stderr.write(`[vcs-router] ${args.map(String).join(' ')}\n`);
}

export interface VcsContext {
  provider: 'github' | 'bitbucket';
  owner: string;        // GitHub org or Bitbucket workspace
  remoteRepo: string;   // actual repo name on the remote (may differ from local name)
  ci: 'github-actions' | 'concourse';
  localRepo: string;    // the repo name as known locally / in Jira labels
}

interface RepoVcsConfig {
  provider: 'github' | 'bitbucket';
  owner?: string;
  remote_repo?: string;
  ci?: 'github-actions' | 'concourse';
}

let _configCache: Record<string, RepoVcsConfig> | null = null;

function loadConfig(): Record<string, RepoVcsConfig> {
  if (_configCache) return _configCache;
  const configPath = join(homedir(), '.claude', 'config', 'repo-vcs.json');
  if (!existsSync(configPath)) {
    _configCache = {};
    return _configCache;
  }
  try {
    _configCache = JSON.parse(readFileSync(configPath, 'utf-8'));
    return _configCache!;
  } catch {
    _configCache = {};
    return _configCache;
  }
}

function detectFromGitRemote(repo: string): { provider: 'github' | 'bitbucket'; owner: string } | null {
  const workspaceRoot = process.env.WORKSPACE_ROOT || process.env.PROJECT_ROOT || (() => {
    for (const rel of ['dev/workspace', 'projects/workspace', 'workspace']) {
      const c = join(homedir(), rel);
      if (existsSync(join(c, '.git'))) return c;
    }
    return join(homedir(), 'dev', 'workspace');
  })();
  const repoDir = join(workspaceRoot, repo);
  try {
    const remoteUrl = execSync('git remote get-url origin', {
      cwd: repoDir,
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe'],
      timeout: 5000,
    }).trim();

    if (remoteUrl.includes('github.com')) {
      const match = remoteUrl.match(/github\.com[/:]([^/]+)\//);
      return { provider: 'github', owner: match?.[1] || '' };
    }
    if (remoteUrl.includes('bitbucket.org')) {
      const match = remoteUrl.match(/bitbucket\.org[/:]([^/]+)\//);
      return { provider: 'bitbucket', owner: match?.[1] || '' };
    }
  } catch {
    // repo dir doesn't exist or no git remote
  }
  return null;
}

function getBitbucketWorkspace(): string {
  // Reuse existing credential resolution
  if (process.env.BITBUCKET_WORKSPACE) return process.env.BITBUCKET_WORKSPACE;
  const settingsPath = join(homedir(), '.claude', 'settings.json');
  if (existsSync(settingsPath)) {
    try {
      const settings = JSON.parse(readFileSync(settingsPath, 'utf-8'));
      return settings.credentials?.bitbucket?.workspace
        || settings.mcpServers?.['bitbucket-mcp']?.env?.BITBUCKET_WORKSPACE
        || '';
    } catch { /* ignore */ }
  }
  return '';
}

export function resolve(repo: string, explicitProvider?: string): VcsContext {
  debug('resolve called:', repo, 'explicit:', explicitProvider);

  // 1. Explicit provider override
  if (explicitProvider === 'github' || explicitProvider === 'bitbucket') {
    const config = loadConfig()[repo];
    const detected = detectFromGitRemote(repo);
    const ctx: VcsContext = {
      provider: explicitProvider,
      owner: config?.owner || detected?.owner || (explicitProvider === 'bitbucket' ? getBitbucketWorkspace() : ''),
      remoteRepo: config?.remote_repo || repo,
      ci: explicitProvider === 'github' ? 'github-actions' : 'concourse',
      localRepo: repo,
    };
    debug('resolved via explicit provider:', JSON.stringify(ctx));
    return ctx;
  }

  // 2. Config file lookup
  const config = loadConfig()[repo];
  if (config) {
    const ctx: VcsContext = {
      provider: config.provider,
      owner: config.owner || (config.provider === 'bitbucket' ? getBitbucketWorkspace() : ''),
      remoteRepo: config.remote_repo || repo,
      ci: config.ci || (config.provider === 'github' ? 'github-actions' : 'concourse'),
      localRepo: repo,
    };
    debug('resolved via config:', JSON.stringify(ctx));
    return ctx;
  }

  // 3. Git remote detection
  const detected = detectFromGitRemote(repo);
  if (detected) {
    const ctx: VcsContext = {
      provider: detected.provider,
      owner: detected.owner,
      remoteRepo: repo,
      ci: detected.provider === 'github' ? 'github-actions' : 'concourse',
      localRepo: repo,
    };
    debug('resolved via git remote:', JSON.stringify(ctx));
    return ctx;
  }

  // 4. Default: bitbucket
  debug('resolved via default (bitbucket) — no config or git remote matched');
  return {
    provider: 'bitbucket',
    owner: getBitbucketWorkspace(),
    remoteRepo: repo,
    ci: 'concourse',
    localRepo: repo,
  };
}

/**
 * Delegate to the appropriate provider skill.
 * Translates unified params to provider-specific params automatically.
 */
export async function delegate(
  ctx: VcsContext,
  skill: string,
  params: Record<string, unknown>
): Promise<unknown> {
  const skillDir = ctx.provider === 'github'
    ? join(homedir(), '.claude', 'skills', 'github-mcp')
    : join(homedir(), '.claude', 'skills', 'bitbucket');

  const translatedParams = translateParams(ctx, skill, params);

  const skillPath = join(skillDir, `${skill}.ts`);
  if (!existsSync(skillPath)) {
    throw new Error(`VCS skill not found: ${skillPath} (provider: ${ctx.provider})`);
  }

  debug('delegate:', ctx.provider, skill, '->', skillPath);
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
    throw new Error(stderr || `VCS skill '${skill}' exited with code ${child.status}`);
  }

  const result = child.stdout;
  try {
    return JSON.parse(result);
  } catch {
    return result; // plain text (e.g., diffs)
  }
}

/**
 * Translate unified parameter names to provider-specific ones.
 */
function translateParams(
  ctx: VcsContext,
  skill: string,
  params: Record<string, unknown>
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...params };

  if (ctx.provider === 'github') {
    // Inject owner, map repo/PR params
    out.owner = out.owner || ctx.owner;
    if ('repo' in out) {
      // Map local repo name to remote repo name
      out.repo = ctx.remoteRepo;
    }
    // Unified pr_number → GitHub pull_number
    if ('pr_number' in out) {
      out.pull_number = out.pr_number;
      delete out.pr_number;
    }
    // Unified comment_text → GitHub body
    if ('comment_text' in out) {
      out.body = out.comment_text;
      delete out.comment_text;
    }
    // Unified source_branch → GitHub head
    if ('source_branch' in out) {
      out.head = out.source_branch;
      delete out.source_branch;
    }
    // Unified target_branch → GitHub base
    if ('target_branch' in out) {
      out.base = out.target_branch;
      delete out.target_branch;
    }
    // Unified description → GitHub body (for PR creation)
    if (skill === 'create_pull_request' && 'description' in out) {
      out.body = out.description;
      delete out.description;
    }
    // Remove provider-specific fields
    delete out.provider;
  } else {
    // Bitbucket
    // Unified repo → repo_slug
    if ('repo' in out) {
      out.repo_slug = ctx.remoteRepo;
      delete out.repo;
    }
    // Unified pr_number → pull_request_id
    if ('pr_number' in out) {
      out.pull_request_id = out.pr_number;
      delete out.pr_number;
    }
    // Unified comment_text → content (raw)
    if ('comment_text' in out) {
      out.content = out.comment_text;
      delete out.comment_text;
    }
    // Remove provider-specific fields
    delete out.provider;
    delete out.owner;
  }

  return out;
}

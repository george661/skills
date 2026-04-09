#!/usr/bin/env npx tsx
/**
 * GitHub REST API Client
 * Uses `gh api` CLI for authentication (keyring-based).
 * Falls back to GITHUB_TOKEN env var + raw fetch if gh is unavailable.
 *
 * Owner resolution order:
 * 1. Explicit `owner` parameter on each call
 * 2. GITHUB_OWNER environment variable
 * 3. Git remote origin URL parsing
 */
import { execSync, spawnSync } from 'child_process';

let _cachedOwner: string | undefined;

export function resolveOwner(explicit?: string): string {
  if (explicit) return explicit;
  if (process.env.GITHUB_OWNER) return process.env.GITHUB_OWNER;
  if (_cachedOwner) return _cachedOwner;

  try {
    const remoteUrl = execSync('git remote get-url origin', {
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe'],
      timeout: 5000,
    }).trim();

    // Match github.com/owner/repo from HTTPS or SSH URLs
    const match = remoteUrl.match(/github\.com[/:]([^/]+)\//);
    if (match) {
      _cachedOwner = match[1];
      return _cachedOwner;
    }
  } catch {
    // git not available or not in a repo
  }

  throw new Error(
    'GitHub owner not found. Set GITHUB_OWNER env var, pass owner parameter, or run from a repo with a github.com remote.'
  );
}

export async function githubApi<T>(
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  path: string,
  body?: Record<string, unknown>
): Promise<T> {
  const args = ['api', path, '--method', method];

  if (body) {
    args.push('--input', '-');
  }

  try {
    const child = spawnSync('gh', args, {
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe'],
      timeout: 30000,
      input: body ? JSON.stringify(body) : undefined,
    });

    if (child.error) throw child.error;
    if (child.status !== 0) {
      throw new Error(`GitHub API error: ${child.stderr?.trim() || `Exit code ${child.status}`}`);
    }

    const result = child.stdout;
    if (!result.trim()) return {} as T;
    return JSON.parse(result) as T;
  } catch (err: any) {
    if (err.message?.startsWith('GitHub API error:')) throw err;
    throw new Error(`GitHub API error: ${err.message}`);
  }
}

/**
 * GitHub API request that returns plain text (e.g., diffs).
 */
export async function githubApiText(
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  path: string,
  headers?: Record<string, string>
): Promise<string> {
  const args = ['api', path, '--method', method];

  if (headers) {
    for (const [key, value] of Object.entries(headers)) {
      args.push('-H', `${key}: ${value}`);
    }
  }

  const child = spawnSync('gh', args, {
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe'],
    timeout: 30000,
  });

  if (child.error) throw child.error;
  if (child.status !== 0) {
    throw new Error(`GitHub API error: ${child.stderr?.trim() || `Exit code ${child.status}`}`);
  }
  return child.stdout;
}

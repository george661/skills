#!/usr/bin/env npx tsx
/**
 * GitHub Issues REST API Client
 * Retrieves credentials from (in order):
 * 1. Environment variables (GITHUB_TOKEN, GITHUB_OWNER, GITHUB_API_URL)
 * 2. $PROJECT_ROOT/.claude/credentials.json → credentials.github
 * 3. $PROJECT_ROOT/.env file
 * 4. ~/.claude/settings.json → credentials.github
 */
import { readFileSync, existsSync } from 'fs';
import { homedir } from 'os';
import { join } from 'path';

/**
 * Load environment variables from a .env file
 */
function loadEnvFile(filePath: string): Record<string, string> {
  const env: Record<string, string> = {};
  if (!existsSync(filePath)) return env;

  try {
    const content = readFileSync(filePath, 'utf-8');
    for (const line of content.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const match = trimmed.match(/^([^=]+)=(.*)$/);
      if (match) {
        const key = match[1].trim();
        let value = match[2].trim();
        if ((value.startsWith('"') && value.endsWith('"')) ||
            (value.startsWith("'") && value.endsWith("'"))) {
          value = value.slice(1, -1);
        }
        env[key] = value;
      }
    }
  } catch {
    // Ignore read errors
  }
  return env;
}

/**
 * Get credentials from .env file in PROJECT_ROOT or current directory
 */
function getEnvFileCredentials(): { token?: string; defaultOwner?: string; apiUrl?: string } {
  const projectRoot = process.env.PROJECT_ROOT || process.cwd();
  const envPath = join(projectRoot, '.env');
  const env = loadEnvFile(envPath);

  return {
    token: env.GITHUB_TOKEN,
    defaultOwner: env.GITHUB_OWNER,
    apiUrl: env.GITHUB_API_URL,
  };
}

/**
 * Load credentials from $PROJECT_ROOT/.claude/credentials.json
 * Supports both { github: {...} } and { credentials: { github: {...} } } formats.
 */
function getProjectCredentials(service: string): Record<string, string> | undefined {
  const projectRoot = process.env.PROJECT_ROOT || process.cwd();
  const credsPath = join(projectRoot, '.claude', 'credentials.json');
  if (!existsSync(credsPath)) return undefined;

  try {
    const raw = JSON.parse(readFileSync(credsPath, 'utf-8'));
    const creds = raw.credentials ?? raw;
    return creds[service] ?? undefined;
  } catch {
    return undefined;
  }
}

export interface GitHubCredentials {
  token: string;
  defaultOwner: string;
  apiUrl: string;
}

export function getGitHubCredentials(): GitHubCredentials {
  // 1. Check environment variables
  if (process.env.GITHUB_TOKEN) {
    return {
      token: process.env.GITHUB_TOKEN,
      defaultOwner: process.env.GITHUB_OWNER || '',
      apiUrl: process.env.GITHUB_API_URL || 'https://api.github.com',
    };
  }

  // 2. Check $PROJECT_ROOT/.claude/credentials.json
  const projCreds = getProjectCredentials('github');
  if (projCreds?.token) {
    return {
      token: projCreds.token,
      defaultOwner: projCreds.defaultOwner || projCreds.owner || '',
      apiUrl: projCreds.apiUrl || 'https://api.github.com',
    };
  }

  // 3. Check .env file in PROJECT_ROOT
  const envCreds = getEnvFileCredentials();
  if (envCreds.token) {
    return {
      token: envCreds.token,
      defaultOwner: envCreds.defaultOwner || '',
      apiUrl: envCreds.apiUrl || 'https://api.github.com',
    };
  }

  // 4. Try ~/.claude/settings.json → credentials.github
  const settingsPath = join(homedir(), '.claude', 'settings.json');
  if (existsSync(settingsPath)) {
    try {
      const settings = JSON.parse(readFileSync(settingsPath, 'utf-8'));
      const creds = settings.credentials?.github;
      if (creds?.token) {
        return {
          token: creds.token,
          defaultOwner: creds.defaultOwner || creds.owner || '',
          apiUrl: creds.apiUrl || 'https://api.github.com',
        };
      }
    } catch {
      // Ignore parse errors
    }
  }

  throw new Error(
    'GitHub credentials not found. Set GITHUB_TOKEN in: ' +
    '(1) environment variables, (2) $PROJECT_ROOT/.claude/credentials.json credentials.github, ' +
    '(3) $PROJECT_ROOT/.env, or (4) ~/.claude/settings.json credentials.github'
  );
}

export async function githubRequest<T>(
  method: string,
  path: string,
  body?: unknown
): Promise<T> {
  const creds = getGitHubCredentials();
  const url = `${creds.apiUrl}${path}`;

  const response = await fetch(url, {
    method,
    headers: {
      'Authorization': `Bearer ${creds.token}`,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  // Rate limit warning
  const remaining = response.headers.get('x-ratelimit-remaining');
  if (remaining !== null && parseInt(remaining, 10) < 10) {
    const reset = response.headers.get('x-ratelimit-reset');
    const resetTime = reset ? new Date(parseInt(reset, 10) * 1000).toISOString() : 'unknown';
    process.stderr.write(`WARNING: GitHub API rate limit low (${remaining} remaining, resets ${resetTime})\n`);
  }

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`GitHub API error (${response.status}): ${error}`);
  }

  if (response.status === 204) {
    return { success: true } as T;
  }

  return response.json();
}

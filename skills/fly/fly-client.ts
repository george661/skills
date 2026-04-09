#!/usr/bin/env npx tsx
/**
 * Fly CLI Client (Concourse CI)
 * Wraps the `fly` CLI tool for Concourse CI operations.
 * Uses browser-based authentication (fly login -b) for token refresh.
 * Retrieves target and URL from (in order):
 * 1. Environment variables (FLY_TARGET, CONCOURSE_URL)
 * 2. $PROJECT_ROOT/.claude/credentials.json
 * 3. $PROJECT_ROOT/.env file
 * 4. ~/.claude/settings.json credentials.fly
 */
import { execSync } from 'child_process';
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
        // Remove surrounding quotes if present
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
function getEnvFileCredentials(): { target?: string; url?: string; username?: string; password?: string } {
  const projectRoot = process.env.PROJECT_ROOT || process.cwd();
  const envPath = join(projectRoot, '.env');
  const env = loadEnvFile(envPath);

  return {
    target: env.FLY_TARGET,
    url: env.CONCOURSE_URL,
    username: env.CONCOURSE_USERNAME,
    password: env.CONCOURSE_PASSWORD,
  };
}

/**
 * Load credentials from $PROJECT_ROOT/.claude/credentials.json
 * Supports both { fly: {...} } and { credentials: { fly: {...} } } formats.
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

export interface FlyCredentials {
  target: string;
  url: string;
  username?: string;
  password?: string;
}

export function getFlyCredentials(): FlyCredentials {
  // 1. Check environment variables (target + url required; username/password optional)
  if (process.env.FLY_TARGET && process.env.CONCOURSE_URL) {
    return {
      target: process.env.FLY_TARGET,
      url: process.env.CONCOURSE_URL,
      username: process.env.CONCOURSE_USERNAME,
      password: process.env.CONCOURSE_PASSWORD,
    };
  }

  // 2. Check $PROJECT_ROOT/.claude/credentials.json
  const projCreds = getProjectCredentials('fly');
  if (projCreds?.target && projCreds?.url) {
    return {
      target: projCreds.target,
      url: projCreds.url,
      username: projCreds.username,
      password: projCreds.password,
    };
  }

  // 3. Check .env file in PROJECT_ROOT
  const envCreds = getEnvFileCredentials();
  if (envCreds.target && envCreds.url) {
    return {
      target: envCreds.target,
      url: envCreds.url,
      username: envCreds.username,
      password: envCreds.password,
    };
  }

  // 4. Try settings.json
  const settingsPath = join(homedir(), '.claude', 'settings.json');
  if (existsSync(settingsPath)) {
    try {
      const settings = JSON.parse(readFileSync(settingsPath, 'utf-8'));

      const creds = settings.credentials?.fly;
      if (creds?.target && creds?.url) {
        return {
          target: creds.target,
          url: creds.url,
          username: creds.username,
          password: creds.password,
        };
      }
    } catch {
      // Ignore parse errors
    }
  }

  throw new Error(
    'Fly credentials not found. Set FLY_TARGET and CONCOURSE_URL in: ' +
    '(1) environment variables, (2) $PROJECT_ROOT/.claude/credentials.json, (3) $PROJECT_ROOT/.env, or (4) ~/.claude/settings.json credentials.fly'
  );
}

export function getFlyTarget(): string {
  return getFlyCredentials().target;
}

/**
 * Check if an error message indicates an expired or invalid token.
 */
function isAuthError(message: string): boolean {
  const lower = message.toLowerCase();
  return lower.includes('not authorized') ||
    lower.includes('unauthorized') ||
    lower.includes('token expired') ||
    lower.includes('401') ||
    lower.includes('forbidden') ||
    lower.includes('not logged in');
}

/**
 * Fetch Concourse local-user credentials from AWS Secrets Manager.
 * Secret: concourse/local-user
 * Returns { username, password } or null if unavailable.
 */
function fetchSecretCredentials(): { username: string; password: string } | null {
  try {
    const raw = execSync(
      'aws secretsmanager get-secret-value --secret-id concourse/local-user --query SecretString --output text',
      { stdio: ['pipe', 'pipe', 'pipe'], timeout: 15000 }
    ).toString().trim();

    // Secret format is "user1:pass1,user2:pass2" — use the first entry
    const firstEntry = raw.split(',')[0];
    if (firstEntry && firstEntry.includes(':')) {
      const [username, ...passwordParts] = firstEntry.split(':');
      const password = passwordParts.join(':'); // password may contain colons
      if (username && password) {
        return { username, password };
      }
    }

    // Fallback: try JSON format
    try {
      const secret = JSON.parse(raw);
      if (secret.username && secret.password) {
        return { username: secret.username, password: secret.password };
      }
    } catch {
      // Not JSON, already handled above
    }

    return null;
  } catch {
    return null;
  }
}

/**
 * Perform login to the Concourse target.
 * Strategy:
 *   1. Try username/password from credentials config (env, .env, settings.json)
 *   2. Try username/password from AWS Secrets Manager (concourse/local-user)
 *   3. Fall back to browser-based login (fly login -b)
 */
function performLogin(): void {
  const creds = getFlyCredentials();

  // Strategy 1: Use username/password from credentials config
  if (creds.username && creds.password) {
    try {
      execSync(
        `fly -t ${creds.target} login -c ${creds.url} -u ${creds.username} -p ${creds.password}`,
        { stdio: 'pipe', timeout: 30000 }
      );
      return;
    } catch {
      // Fall through to next strategy
    }
  }

  // Strategy 2: Fetch credentials from AWS Secrets Manager
  const secretCreds = fetchSecretCredentials();
  if (secretCreds) {
    try {
      execSync(
        `fly -t ${creds.target} login -c ${creds.url} -u ${secretCreds.username} -p ${secretCreds.password}`,
        { stdio: 'pipe', timeout: 30000 }
      );
      return;
    } catch {
      // Fall through to browser login
    }
  }

  // Strategy 3: Browser-based login (original behavior)
  const loginCmd = `fly -t ${creds.target} login -c ${creds.url} -b`;
  try {
    execSync(loginCmd, { stdio: 'inherit', timeout: 120000 });
  } catch (loginErr) {
    const msg = loginErr instanceof Error ? loginErr.message : String(loginErr);
    throw new Error(`Failed to login to Concourse target "${creds.target}": ${msg}`);
  }
}

/**
 * Ensure the fly CLI is logged in to the configured target.
 * If not logged in, performs a browser-based login.
 */
function ensureLoggedIn(): void {
  const creds = getFlyCredentials();

  try {
    // Check if already logged in by running a simple command
    execSync(`fly -t ${creds.target} status`, { stdio: 'pipe', timeout: 10000 });
  } catch {
    // Not logged in or token expired, perform browser-based login
    performLogin();
  }
}

/**
 * Execute a fly CLI command and return stdout as a string.
 * Automatically prefixes with `-t {target}` and ensures login.
 * If the command fails due to an expired token, re-authenticates and retries once.
 *
 * @param args - Array of fly command arguments (e.g., ['pipelines', '--json'])
 * @returns stdout output as a string
 */
export function flyExec(args: string[]): string {
  ensureLoggedIn();
  const target = getFlyTarget();
  const cmd = `fly -t ${target} ${args.join(' ')}`;

  try {
    const output = execSync(cmd, { stdio: ['pipe', 'pipe', 'pipe'], timeout: 120000, maxBuffer: 10 * 1024 * 1024 });
    return output.toString().trim();
  } catch (err) {
    const errMsg = err && typeof err === 'object' && 'stderr' in err
      ? (err as { stderr: Buffer }).stderr.toString().trim()
      : (err instanceof Error ? err.message : String(err));

    // If the error is auth-related, re-login and retry the command once
    if (isAuthError(errMsg)) {
      performLogin();
      try {
        const output = execSync(cmd, { stdio: ['pipe', 'pipe', 'pipe'], timeout: 120000, maxBuffer: 10 * 1024 * 1024 });
        return output.toString().trim();
      } catch (retryErr) {
        const retryMsg = retryErr && typeof retryErr === 'object' && 'stderr' in retryErr
          ? (retryErr as { stderr: Buffer }).stderr.toString().trim()
          : (retryErr instanceof Error ? retryErr.message : String(retryErr));
        throw new Error(`fly command failed after re-authentication: ${retryMsg}`);
      }
    }

    throw new Error(`fly command failed: ${errMsg}`);
  }
}

/**
 * Execute a fly CLI command with --json flag and parse the JSON output.
 * Automatically prefixes with `-t {target}` and ensures login.
 *
 * @param args - Array of fly command arguments (--json is appended automatically)
 * @returns Parsed JSON response
 */
export function flyExecJson<T>(args: string[]): T {
  const output = flyExec([...args, '--json']);
  try {
    return JSON.parse(output) as T;
  } catch {
    throw new Error(`Failed to parse fly JSON output: ${output.substring(0, 200)}`);
  }
}

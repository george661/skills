#!/usr/bin/env npx tsx
/**
 * Concourse CI REST API Client
 * Retrieves credentials from (in order):
 * 1. ~/.flyrc (fly CLI token — always preferred; refreshed by `fly login`)
 * 2. Environment variables (CONCOURSE_URL, CONCOURSE_TEAM, CONCOURSE_USERNAME, CONCOURSE_PASSWORD, CONCOURSE_TOKEN)
 * 3. $PROJECT_ROOT/.claude/credentials.json
 * 4. $PROJECT_ROOT/.env file
 * 5. ~/.claude/settings.json credentials.concourse
 *
 * flyrc is checked first because CONCOURSE_TOKEN in .env goes stale between
 * `fly login` sessions. The flyrc token is always the freshest available.
 */
import { readFileSync, existsSync } from 'fs';
import { homedir } from 'os';
import { join } from 'path';

/**
 * Read the fly CLI token from ~/.flyrc for a given target URL.
 * Parses the YAML by line rather than adding a YAML dependency.
 * Returns {url, team, token} if a matching target is found.
 */
function getFlyrcCredentials(matchUrl?: string): { url: string; team: string; token: string } | undefined {
  const flyrcPath = join(homedir(), '.flyrc');
  if (!existsSync(flyrcPath)) return undefined;

  try {
    const content = readFileSync(flyrcPath, 'utf-8');
    const lines = content.split('\n');

    // Collect targets: name → {api, team, tokenValue}
    const targets: Record<string, { api?: string; team?: string; tokenValue?: string }> = {};
    let currentTarget: string | null = null;
    let inToken = false;

    for (const raw of lines) {
      const line = raw.trimEnd();

      // Top-level target name (2-space indent key under "targets:")
      const targetMatch = line.match(/^  ([^\s:]+):\s*$/);
      if (targetMatch) {
        const name = targetMatch[1];
        currentTarget = name;
        targets[name] = {};
        inToken = false;
        continue;
      }

      if (!currentTarget) continue;

      const apiMatch = line.match(/^\s+api:\s*(.+)$/);
      if (apiMatch) { targets[currentTarget].api = apiMatch[1].trim(); continue; }

      const teamMatch = line.match(/^\s+team:\s*(.+)$/);
      if (teamMatch) { targets[currentTarget].team = teamMatch[1].trim(); continue; }

      if (line.match(/^\s+token:\s*$/)) { inToken = true; continue; }

      if (inToken) {
        const valMatch = line.match(/^\s+value:\s*(.+)$/);
        if (valMatch) {
          targets[currentTarget].tokenValue = valMatch[1].trim();
          inToken = false;
        }
      }
    }

    // Pick the best matching target: exact URL match first, then first valid token
    const normalise = (u: string) => u.replace(/\/$/, '');
    const norm = matchUrl ? normalise(matchUrl) : undefined;

    const sorted = Object.values(targets).filter(t => t.api && t.team && t.tokenValue);
    const match = norm
      ? sorted.find(t => normalise(t.api!) === norm)
      : sorted[0];

    if (match) {
      return { url: normalise(match.api!), team: match.team!, token: match.tokenValue! };
    }
  } catch {
    // Ignore read/parse errors
  }
  return undefined;
}

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
function getEnvFileCredentials(): {
  url?: string;
  team?: string;
  username?: string;
  password?: string;
  token?: string;
} {
  const projectRoot = process.env.PROJECT_ROOT || process.cwd();
  const envPath = join(projectRoot, '.env');
  const env = loadEnvFile(envPath);

  return {
    url: env.CONCOURSE_URL,
    team: env.CONCOURSE_TEAM,
    username: env.CONCOURSE_USERNAME,
    password: env.CONCOURSE_PASSWORD,
    token: env.CONCOURSE_TOKEN,
  };
}

/**
 * Load credentials from $PROJECT_ROOT/.claude/credentials.json
 * Supports both { concourse: {...} } and { credentials: { concourse: {...} } } formats.
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

export interface ConcourseCredentials {
  url: string;
  team: string;
  username?: string;
  password?: string;
  token?: string;
}

export function getConcourseCredentials(): ConcourseCredentials {
  // 1. Check ~/.flyrc — freshest token, updated by `fly login`
  const flyrcCreds = getFlyrcCredentials(process.env.CONCOURSE_URL);
  if (flyrcCreds) {
    return flyrcCreds;
  }

  // 2. Check environment variables
  if (process.env.CONCOURSE_URL && process.env.CONCOURSE_TEAM) {
    if (process.env.CONCOURSE_TOKEN) {
      return {
        url: process.env.CONCOURSE_URL.replace(/\/$/, ''),
        team: process.env.CONCOURSE_TEAM,
        token: process.env.CONCOURSE_TOKEN,
      };
    }
    if (process.env.CONCOURSE_USERNAME && process.env.CONCOURSE_PASSWORD) {
      return {
        url: process.env.CONCOURSE_URL.replace(/\/$/, ''),
        team: process.env.CONCOURSE_TEAM,
        username: process.env.CONCOURSE_USERNAME,
        password: process.env.CONCOURSE_PASSWORD,
      };
    }
  }

  // 3. Check $PROJECT_ROOT/.claude/credentials.json
  const projCreds = getProjectCredentials('concourse');
  if (projCreds?.url && projCreds?.team) {
    if (projCreds.token) {
      return {
        url: projCreds.url.replace(/\/$/, ''),
        team: projCreds.team,
        token: projCreds.token,
      };
    }
    if (projCreds.username && projCreds.password) {
      return {
        url: projCreds.url.replace(/\/$/, ''),
        team: projCreds.team,
        username: projCreds.username,
        password: projCreds.password,
      };
    }
  }

  // 4. Check .env file in PROJECT_ROOT
  const envCreds = getEnvFileCredentials();
  if (envCreds.url && envCreds.team) {
    if (envCreds.token) {
      return {
        url: envCreds.url.replace(/\/$/, ''),
        team: envCreds.team,
        token: envCreds.token,
      };
    }
    if (envCreds.username && envCreds.password) {
      return {
        url: envCreds.url.replace(/\/$/, ''),
        team: envCreds.team,
        username: envCreds.username,
        password: envCreds.password,
      };
    }
  }

  // 5. Try settings.json
  const settingsPath = join(homedir(), '.claude', 'settings.json');
  if (existsSync(settingsPath)) {
    try {
      const settings = JSON.parse(readFileSync(settingsPath, 'utf-8'));

      const creds = settings.credentials?.concourse;
      if (creds?.url && creds?.team) {
        if (creds.token) {
          return {
            url: creds.url.replace(/\/$/, ''),
            team: creds.team,
            token: creds.token,
          };
        }
        if (creds.username && creds.password) {
          return {
            url: creds.url.replace(/\/$/, ''),
            team: creds.team,
            username: creds.username,
            password: creds.password,
          };
        }
      }
    } catch {
      // Ignore parse errors
    }
  }

  throw new Error(
    'Concourse credentials not found. Run `fly -t ${CI_TARGET} login` to refresh ~/.flyrc, or set CONCOURSE_URL, CONCOURSE_TEAM, and either CONCOURSE_TOKEN or CONCOURSE_USERNAME + CONCOURSE_PASSWORD in: ' +
    '(1) ~/.flyrc, (2) environment variables, (3) $PROJECT_ROOT/.claude/credentials.json, (4) $PROJECT_ROOT/.env, or (5) ~/.claude/settings.json credentials.concourse'
  );
}

/** Cached auth token for username/password authentication */
let cachedToken: string | null = null;

/**
 * Authenticate with Concourse using username/password and return a bearer token.
 * Uses the sky/issuer/token endpoint with password grant type.
 */
async function authenticate(creds: ConcourseCredentials): Promise<string> {
  if (cachedToken) return cachedToken;

  if (creds.token) {
    cachedToken = creds.token;
    return cachedToken;
  }

  if (!creds.username || !creds.password) {
    throw new Error('Concourse authentication requires either a token or username + password');
  }

  const tokenUrl = `${creds.url}/sky/issuer/token`;
  const body = new URLSearchParams({
    grant_type: 'password',
    username: creds.username,
    password: creds.password,
    scope: 'openid profile email federated:id groups',
  });

  const response = await fetch(tokenUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'Authorization': `Basic ${Buffer.from('fly:Zmx5').toString('base64')}`,
    },
    body: body.toString(),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Concourse authentication failed (${response.status}): ${error}`);
  }

  const data = await response.json() as { access_token: string };
  cachedToken = data.access_token;
  return cachedToken;
}

export async function concourseRequest<T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  path: string,
  body?: Record<string, unknown>
): Promise<T> {
  const creds = getConcourseCredentials();
  const token = await authenticate(creds);

  const url = `${creds.url}${path}`;

  const headers: Record<string, string> = {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json',
  };

  const response = await fetch(url, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Concourse API error (${response.status}): ${error}`);
  }

  if (response.status === 204) {
    return { success: true } as T;
  }

  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return response.json();
  }

  // Some endpoints return plain text or YAML
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text } as T;
  }
}

export function getTeam(): string {
  return getConcourseCredentials().team;
}

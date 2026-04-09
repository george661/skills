#!/usr/bin/env npx tsx
/**
 * Linear GraphQL API Client
 * Retrieves credentials from (in order):
 * 1. Environment variables (LINEAR_API_KEY, LINEAR_TEAM_KEY)
 * 2. $PROJECT_ROOT/.claude/credentials.json → credentials.linear
 * 3. $PROJECT_ROOT/.env file
 * 4. ~/.claude/settings.json → credentials.linear
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
function getEnvFileCredentials(): { apiKey?: string; teamKey?: string } {
  const projectRoot = process.env.PROJECT_ROOT || process.cwd();
  const envPath = join(projectRoot, '.env');
  const env = loadEnvFile(envPath);

  return {
    apiKey: env.LINEAR_API_KEY,
    teamKey: env.LINEAR_TEAM_KEY,
  };
}

/**
 * Load credentials from $PROJECT_ROOT/.claude/credentials.json
 * Supports both { linear: {...} } and { credentials: { linear: {...} } } formats.
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

export interface LinearCredentials {
  apiKey: string;
  teamKey: string;
}

export function getLinearCredentials(): LinearCredentials {
  // 1. Check environment variables
  if (process.env.LINEAR_API_KEY) {
    return {
      apiKey: process.env.LINEAR_API_KEY,
      teamKey: process.env.LINEAR_TEAM_KEY || '',
    };
  }

  // 2. Check $PROJECT_ROOT/.claude/credentials.json
  const projCreds = getProjectCredentials('linear');
  if (projCreds?.apiKey) {
    return {
      apiKey: projCreds.apiKey,
      teamKey: projCreds.teamKey || '',
    };
  }

  // 3. Check .env file in PROJECT_ROOT
  const envCreds = getEnvFileCredentials();
  if (envCreds.apiKey) {
    return {
      apiKey: envCreds.apiKey,
      teamKey: envCreds.teamKey || '',
    };
  }

  // 4. Try ~/.claude/settings.json → credentials.linear
  const settingsPath = join(homedir(), '.claude', 'settings.json');
  if (existsSync(settingsPath)) {
    try {
      const settings = JSON.parse(readFileSync(settingsPath, 'utf-8'));
      const creds = settings.credentials?.linear;
      if (creds?.apiKey) {
        return {
          apiKey: creds.apiKey,
          teamKey: creds.teamKey || '',
        };
      }
    } catch {
      // Ignore parse errors
    }
  }

  throw new Error(
    'Linear credentials not found. Set LINEAR_API_KEY in: ' +
    '(1) environment variables, (2) $PROJECT_ROOT/.claude/credentials.json credentials.linear, ' +
    '(3) $PROJECT_ROOT/.env, or (4) ~/.claude/settings.json credentials.linear'
  );
}

export async function linearQuery<T>(
  query: string,
  variables?: Record<string, unknown>
): Promise<T> {
  const { apiKey } = getLinearCredentials();

  const response = await fetch('https://api.linear.app/graphql', {
    method: 'POST',
    headers: {
      'Authorization': apiKey,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ query, variables }),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Linear API error (${response.status}): ${error}`);
  }

  const json = await response.json() as { data?: T; errors?: Array<{ message: string }> };

  if (json.errors?.length) {
    throw new Error(`Linear GraphQL error: ${json.errors.map((e) => e.message).join('; ')}`);
  }

  return json.data as T;
}

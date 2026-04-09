/**
 * AgentDB REST API Client
 *
 * Provides a simple HTTP client for AgentDB REST API endpoints.
 * Retrieves credentials from (in order):
 * 1. Environment variables (AGENTDB_API_KEY, AGENTDB_URL)
 * 2. $PROJECT_ROOT/.claude/credentials.json
 * 3. $PROJECT_ROOT/.env file
 * 4. ~/.claude/settings.json credentials.agentdb
 * 5. ~/.claude/settings.json mcpServers.agentdb (legacy fallback)
 * 6. AWS Secrets Manager (agentdb-dev-api-key)
 */

import { readFileSync, existsSync } from 'fs';
import { homedir } from 'os';
import { join } from 'path';
import { execSync } from 'child_process';

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
function getEnvFileCredentials(): { apiKey?: string; url?: string } {
  const projectRoot = process.env.PROJECT_ROOT || process.cwd();
  const envPath = join(projectRoot, '.env');
  const env = loadEnvFile(envPath);

  return {
    apiKey: env.AGENTDB_API_KEY,
    url: env.AGENTDB_URL,
  };
}

/**
 * Load credentials from $PROJECT_ROOT/.claude/credentials.json
 * Supports both { agentdb: {...} } and { credentials: { agentdb: {...} } } formats.
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

export interface AgentDBCredentials {
  apiKey: string;
  url: string;
}

const DEFAULT_AGENTDB_URL = process.env.AGENTDB_URL || 'YOUR_AGENTDB_URL';

/**
 * Get AgentDB credentials from environment, settings, or Secrets Manager
 */
export function getAgentDBCredentials(): AgentDBCredentials {
  // 1. Check environment variables
  if (process.env.AGENTDB_API_KEY) {
    return {
      apiKey: process.env.AGENTDB_API_KEY,
      url: process.env.AGENTDB_URL || DEFAULT_AGENTDB_URL,
    };
  }

  // 2. Check $PROJECT_ROOT/.claude/credentials.json
  const projCreds = getProjectCredentials('agentdb');
  if (projCreds?.apiKey) {
    return {
      apiKey: projCreds.apiKey,
      url: projCreds.url || DEFAULT_AGENTDB_URL,
    };
  }

  // 3. Check .env file in PROJECT_ROOT
  const envCreds = getEnvFileCredentials();
  if (envCreds.apiKey) {
    return {
      apiKey: envCreds.apiKey,
      url: envCreds.url || DEFAULT_AGENTDB_URL,
    };
  }

  // 4. Try settings.json
  const settingsPath = join(homedir(), '.claude', 'settings.json');
  if (existsSync(settingsPath)) {
    try {
      const settings = JSON.parse(readFileSync(settingsPath, 'utf-8'));

      const creds = settings.credentials?.agentdb;
      if (creds?.apiKey) {
        return {
          apiKey: creds.apiKey,
          url: creds.url || DEFAULT_AGENTDB_URL,
        };
      }

      // 2b. Legacy mcpServers location (fallback)
      const config = settings.mcpServers?.['agentdb'];
      if (config?.headers?.['X-Api-Key']) {
        // Strip /sse suffix from legacy URL if present
        let legacyUrl = config.url || DEFAULT_AGENTDB_URL;
        if (legacyUrl.endsWith('/sse')) {
          legacyUrl = legacyUrl.slice(0, -4);
        }
        return {
          apiKey: config.headers['X-Api-Key'],
          url: legacyUrl,
        };
      }
    } catch {
      // Settings not readable, continue to fallback
    }
  }

  // 3. Try AWS Secrets Manager
  try {
    const awsProfile = process.env.AWS_PROFILE || 'default';
    const secretJson = execSync(
      `AWS_PROFILE=${awsProfile} aws secretsmanager get-secret-value ` +
      `--secret-id agentdb-mcp-dev-api-key --query SecretString --output text 2>/dev/null`,
      { encoding: 'utf-8', timeout: 10000 }
    ).trim();

    if (secretJson) {
      const secret = JSON.parse(secretJson);
      if (secret.apiKey) {
        return {
          apiKey: secret.apiKey,
          url: process.env.AGENTDB_URL || DEFAULT_AGENTDB_URL,
        };
      }
    }
  } catch {
    // Secrets Manager not available, continue
  }

  throw new Error(
    'AgentDB credentials not found. Set AGENTDB_API_KEY in: ' +
    '(1) environment variables, (2) $PROJECT_ROOT/.claude/credentials.json, (3) $PROJECT_ROOT/.env, ' +
    '(4) ~/.claude/settings.json credentials.agentdb, or (5) ensure AWS credentials for Secrets Manager'
  );
}

/**
 * Get API key (legacy helper, use getAgentDBCredentials for full credentials)
 */
export function getApiKey(): string {
  return getAgentDBCredentials().apiKey;
}

/**
 * Make a REST API request to AgentDB
 */
export async function agentdbRequest<T>(
  method: 'GET' | 'POST',
  path: string,
  body?: Record<string, unknown>
): Promise<T> {
  const credentials = getAgentDBCredentials();
  const url = `${credentials.url}${path}`;

  const response = await fetch(url, {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-Api-Key': credentials.apiKey,
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: response.statusText }));
    throw new Error(`AgentDB API error (${response.status}): ${error.error || JSON.stringify(error)}`);
  }

  return response.json();
}

// Export base URL for reference
export { DEFAULT_AGENTDB_URL };

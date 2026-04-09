#!/usr/bin/env npx tsx
/**
 * Slack REST API Client
 * Retrieves credentials from (in order):
 * 1. Environment variables (SLACK_BOT_TOKEN, SLACK_DEFAULT_CHANNEL)
 * 2. $PROJECT_ROOT/.claude/credentials.json
 * 3. $PROJECT_ROOT/.env file
 * 4. ~/.claude/settings.json credentials.slack
 * 5. ~/.claude/settings.json mcpServers.slack-mcp.env (legacy fallback)
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
function getEnvFileCredentials(): { botToken?: string; defaultChannel?: string } {
  const projectRoot = process.env.PROJECT_ROOT || process.cwd();
  const envPath = join(projectRoot, '.env');
  const env = loadEnvFile(envPath);

  return {
    botToken: env.SLACK_BOT_TOKEN,
    defaultChannel: env.SLACK_DEFAULT_CHANNEL,
  };
}

/**
 * Load credentials from $PROJECT_ROOT/.claude/credentials.json
 * Supports both { slack: {...} } and { credentials: { slack: {...} } } formats.
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

export interface SlackCredentials {
  botToken: string;
  defaultChannel?: string;
}

export function getSlackCredentials(): SlackCredentials {
  // 1. Check environment variables
  if (process.env.SLACK_BOT_TOKEN) {
    return {
      botToken: process.env.SLACK_BOT_TOKEN,
      defaultChannel: process.env.SLACK_DEFAULT_CHANNEL,
    };
  }

  // 2. Check $PROJECT_ROOT/.claude/credentials.json
  const projCreds = getProjectCredentials('slack');
  if (projCreds?.botToken) {
    return {
      botToken: projCreds.botToken,
      defaultChannel: projCreds.defaultChannel,
    };
  }

  // 3. Check .env file in PROJECT_ROOT
  const envCreds = getEnvFileCredentials();
  if (envCreds.botToken) {
    return {
      botToken: envCreds.botToken,
      defaultChannel: envCreds.defaultChannel,
    };
  }

  // 4. Try settings.json
  const settingsPath = join(homedir(), '.claude', 'settings.json');
  if (existsSync(settingsPath)) {
    try {
      const settings = JSON.parse(readFileSync(settingsPath, 'utf-8'));

      const creds = settings.credentials?.slack;
      if (creds?.botToken) {
        return {
          botToken: creds.botToken,
          defaultChannel: creds.defaultChannel,
        };
      }

      // 2b. Legacy mcpServers location (fallback)
      const env = settings.mcpServers?.['slack-mcp']?.env;
      if (env?.SLACK_BOT_TOKEN) {
        return {
          botToken: env.SLACK_BOT_TOKEN,
          defaultChannel: env.SLACK_DEFAULT_CHANNEL,
        };
      }
    } catch {
      // Ignore parse errors
    }
  }

  throw new Error(
    'Slack credentials not found. Set SLACK_BOT_TOKEN in: ' +
    '(1) environment variables, (2) $PROJECT_ROOT/.claude/credentials.json, (3) $PROJECT_ROOT/.env, or (4) ~/.claude/settings.json credentials.slack'
  );
}

export async function slackRequest<T>(
  method: string,
  body: Record<string, unknown>
): Promise<T> {
  const creds = getSlackCredentials();
  const url = `https://slack.com/api/${method}`;

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${creds.botToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Slack API error (${response.status}): ${error}`);
  }

  return response.json();
}

export function getDefaultChannel(): string | undefined {
  try {
    return getSlackCredentials().defaultChannel;
  } catch {
    return undefined;
  }
}

#!/usr/bin/env npx tsx
/**
 * migrate-credentials.ts
 *
 * Migrates credentials from .env and ~/.claude/settings.json
 * into $PROJECT_ROOT/.claude/credentials.json
 */

import { readFileSync, writeFileSync, appendFileSync, existsSync, mkdirSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';

interface Credentials {
  jira?: { host: string; username: string; apiToken: string };
  bitbucket?: { workspace: string; username: string; token: string; default_branch: string };
  agentdb?: { apiKey: string; url: string };
  slack?: { botToken: string; defaultChannel: string };
  concourse?: { url: string; team: string; token: string };
}

// Env var -> credential field mapping
const ENV_MAP: Record<string, { service: string; field: string }> = {
  JIRA_HOST: { service: 'jira', field: 'host' },
  JIRA_USERNAME: { service: 'jira', field: 'username' },
  JIRA_EMAIL: { service: 'jira', field: 'username' },
  JIRA_API_TOKEN: { service: 'jira', field: 'apiToken' },
  BITBUCKET_WORKSPACE: { service: 'bitbucket', field: 'workspace' },
  BITBUCKET_USERNAME: { service: 'bitbucket', field: 'username' },
  BITBUCKET_TOKEN: { service: 'bitbucket', field: 'token' },
  AGENTDB_API_KEY: { service: 'agentdb', field: 'apiKey' },
  AGENTDB_URL: { service: 'agentdb', field: 'url' },
  SLACK_BOT_TOKEN: { service: 'slack', field: 'botToken' },
  SLACK_DEFAULT_CHANNEL: { service: 'slack', field: 'defaultChannel' },
  CONCOURSE_URL: { service: 'concourse', field: 'url' },
  CONCOURSE_TEAM: { service: 'concourse', field: 'team' },
  CONCOURSE_TOKEN: { service: 'concourse', field: 'token' },
};

const DEFAULTS: Record<string, Record<string, string>> = {
  bitbucket: { default_branch: 'main' },
  agentdb: { url: process.env.AGENTDB_URL || 'YOUR_AGENTDB_URL' },
};

export function extractCredentialsFromEnv(envContent: string): Credentials {
  const creds: Record<string, Record<string, string>> = {};

  for (const line of envContent.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const match = trimmed.match(/^([^=]+)=(.*)$/);
    if (!match) continue;

    const key = match[1].trim();
    let value = match[2].trim();
    if ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }

    const mapping = ENV_MAP[key];
    if (mapping) {
      creds[mapping.service] = creds[mapping.service] ?? {};
      creds[mapping.service][mapping.field] = value;
    }
  }

  for (const [service, defaults] of Object.entries(DEFAULTS)) {
    if (creds[service]) {
      for (const [field, defaultVal] of Object.entries(defaults)) {
        creds[service][field] = creds[service][field] ?? defaultVal;
      }
    }
  }

  return creds as Credentials;
}

export function extractCredentialsFromSettings(settingsPath: string): Credentials {
  if (!existsSync(settingsPath)) return {};
  try {
    const settings = JSON.parse(readFileSync(settingsPath, 'utf-8'));
    return settings.credentials ?? {};
  } catch {
    return {};
  }
}

export function mergeIntoSettings(
  existing: Record<string, unknown>,
  newCreds: Credentials
): Record<string, unknown> & { credentials: Credentials } {
  const existingCreds = (existing.credentials ?? {}) as Credentials;

  const merged: Record<string, Record<string, string>> = {};
  for (const service of new Set([...Object.keys(existingCreds), ...Object.keys(newCreds)])) {
    const existingService = (existingCreds as Record<string, Record<string, string>>)[service] ?? {};
    const newService = (newCreds as Record<string, Record<string, string>>)[service] ?? {};
    merged[service] = { ...newService, ...existingService };
  }

  return { ...existing, credentials: merged as unknown as Credentials };
}

export function migrate(projectRoot: string, dryRun: boolean): {
  migrated: string[];
  skipped: string[];
} {
  const migrated: string[] = [];
  const skipped: string[] = [];

  const envPath = join(projectRoot, '.env');
  const envCreds = existsSync(envPath)
    ? extractCredentialsFromEnv(readFileSync(envPath, 'utf-8'))
    : {};

  const globalSettingsPath = join(homedir(), '.claude', 'settings.json');
  const globalCreds = extractCredentialsFromSettings(globalSettingsPath);

  const allCreds: Credentials = {};
  for (const service of new Set([...Object.keys(globalCreds), ...Object.keys(envCreds)])) {
    const global = (globalCreds as Record<string, Record<string, string>>)[service] ?? {};
    const env = (envCreds as Record<string, Record<string, string>>)[service] ?? {};
    (allCreds as Record<string, Record<string, string>>)[service] = { ...global, ...env };
  }

  if (Object.keys(allCreds).length === 0) {
    skipped.push('No credentials found in .env or ~/.claude/settings.json');
    return { migrated, skipped };
  }

  const targetPath = join(projectRoot, '.claude', 'credentials.json');
  const existing = existsSync(targetPath)
    ? JSON.parse(readFileSync(targetPath, 'utf-8'))
    : {};

  const result = mergeIntoSettings(existing, allCreds);

  for (const service of Object.keys(allCreds)) {
    const existingService = (existing.credentials ?? {})[service];
    if (existingService) {
      skipped.push(`${service}: already in project settings.json`);
    } else {
      migrated.push(service);
    }
  }

  if (!dryRun && migrated.length > 0) {
    mkdirSync(join(projectRoot, '.claude'), { recursive: true });

    if (existsSync(targetPath)) {
      writeFileSync(targetPath + '.bak', readFileSync(targetPath, 'utf-8'));
    }

    const gitignorePath = join(projectRoot, '.gitignore');
    if (existsSync(gitignorePath)) {
      const gitignore = readFileSync(gitignorePath, 'utf-8');
      if (!gitignore.includes('.claude/credentials.json')) {
        appendFileSync(gitignorePath, '\n# Credentials (auto-added by rx)\n.claude/credentials.json\n');
        migrated.push('gitignore entry added');
      }
    }

    writeFileSync(targetPath, JSON.stringify(result, null, 2) + '\n');
  }

  return { migrated, skipped };
}

// CLI entry point
if (!process.env.VITEST && import.meta.url === `file://${process.argv[1]}`) {
  const projectRoot = process.env.PROJECT_ROOT ?? process.env.WORKSPACE_ROOT ?? (() => {
    for (const rel of ['dev/workspace', 'projects/workspace', 'workspace']) {
      const c = join(homedir(), rel);
      if (existsSync(join(c, '.git'))) return c;
    }
    return join(homedir(), 'dev', 'workspace');
  })();
  const dryRun = process.argv.includes('--dry-run');
  const result = migrate(projectRoot, dryRun);
  console.log(JSON.stringify(result, null, 2));
}

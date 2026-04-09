#!/usr/bin/env npx tsx
/**
 * Jira REST API Client
 * Retrieves credentials from (in order):
 * 1. Environment variables (JIRA_HOST, JIRA_USERNAME, JIRA_API_TOKEN)
 * 2. $PROJECT_ROOT/.claude/credentials.json
 * 3. $PROJECT_ROOT/.env file
 * 4. ~/.claude/settings.json credentials.jira
 * 5. ~/.claude/settings.json mcpServers.jira-mcp.env (legacy fallback)
 * 6. AWS SSM Parameter Store (SSM_CREDENTIALS_PATH or /issue-daemon/dev/config)
 */
import { readFileSync, existsSync } from 'fs';
import { readFile } from 'fs/promises';
import { execSync } from 'child_process';
import { homedir } from 'os';
import { join, basename } from 'path';

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
function getEnvFileCredentials(): { host?: string; username?: string; apiToken?: string; costFieldId?: string } {
  const projectRoot = process.env.PROJECT_ROOT || process.cwd();
  const envPath = join(projectRoot, '.env');
  const env = loadEnvFile(envPath);

  return {
    host: env.JIRA_HOST,
    username: env.JIRA_USERNAME,
    apiToken: env.JIRA_API_TOKEN,
    costFieldId: env.JIRA_COST_FIELD_ID,
  };
}

/**
 * Load credentials from $PROJECT_ROOT/.claude/credentials.json
 * Supports both { jira: {...} } and { credentials: { jira: {...} } } formats.
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


/**
 * Fetch credentials from AWS SSM Parameter Store.
 * Uses the AWS CLI so no SDK dependency is needed.
 */
function getSsmCredentials(service: string): Record<string, string> | undefined {
  const ssmPath = process.env.SSM_CREDENTIALS_PATH || '/issue-daemon/dev/config';
  try {
    const raw = execSync(
      `aws ssm get-parameter --name "${ssmPath}" --with-decryption --query 'Parameter.Value' --output text`,
      { timeout: 5000, encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] }
    );
    const config = JSON.parse(raw.trim());
    return config[service] ?? undefined;
  } catch {
    return undefined;
  }
}

export interface JiraCredentials {
  host: string;
  username: string;
  apiToken: string;
}

export function getJiraCredentials(): JiraCredentials {
  // 1. Check environment variables
  if (process.env.JIRA_HOST && process.env.JIRA_USERNAME && process.env.JIRA_API_TOKEN) {
    return {
      host: process.env.JIRA_HOST,
      username: process.env.JIRA_USERNAME,
      apiToken: process.env.JIRA_API_TOKEN,
    };
  }

  // 2. Check $PROJECT_ROOT/.claude/credentials.json
  const projCreds = getProjectCredentials('jira');
  if (projCreds?.host && projCreds?.username && projCreds?.apiToken) {
    return {
      host: projCreds.host,
      username: projCreds.username,
      apiToken: projCreds.apiToken,
    };
  }

  // 3. Check .env file in PROJECT_ROOT
  const envCreds = getEnvFileCredentials();
  if (envCreds.host && envCreds.username && envCreds.apiToken) {
    return {
      host: envCreds.host,
      username: envCreds.username,
      apiToken: envCreds.apiToken,
    };
  }

  // 4. Try settings.json
  const settingsPath = join(homedir(), '.claude', 'settings.json');
  if (existsSync(settingsPath)) {
    try {
      const settings = JSON.parse(readFileSync(settingsPath, 'utf-8'));

      const creds = settings.credentials?.jira;
      if (creds?.host && creds?.username && creds?.apiToken) {
        return {
          host: creds.host,
          username: creds.username,
          apiToken: creds.apiToken,
        };
      }

      // 2b. Legacy mcpServers location (fallback)
      const env = settings.mcpServers?.['jira-mcp']?.env;
      if (env?.JIRA_HOST && env?.JIRA_USERNAME && env?.JIRA_API_TOKEN) {
        return {
          host: env.JIRA_HOST,
          username: env.JIRA_USERNAME,
          apiToken: env.JIRA_API_TOKEN,
        };
      }
    } catch {
      // Ignore parse errors
    }
  }

  // 6. Try AWS SSM Parameter Store
  const ssmCreds = getSsmCredentials('jira');
  if (ssmCreds?.host && ssmCreds?.username && ssmCreds?.apiToken) {
    return {
      host: ssmCreds.host,
      username: ssmCreds.username,
      apiToken: ssmCreds.apiToken,
    };
  }

  throw new Error(
    'Jira credentials not found. Set JIRA_HOST, JIRA_USERNAME, JIRA_API_TOKEN in: ' +
    '(1) environment variables, (2) $PROJECT_ROOT/.claude/credentials.json, (3) $PROJECT_ROOT/.env, (4) ~/.claude/settings.json credentials.jira, or (6) AWS SSM at SSM_CREDENTIALS_PATH'
  );
}

/**
 * Returns the custom field ID for the Cost field, or undefined if not configured.
 * Reads JIRA_COST_FIELD_ID from (in order):
 * 1. JIRA_COST_FIELD_ID environment variable
 * 2. $PROJECT_ROOT/.env file
 */
export function getJiraCostFieldId(): string | undefined {
  if (process.env.JIRA_COST_FIELD_ID) {
    return process.env.JIRA_COST_FIELD_ID;
  }
  const envCreds = getEnvFileCredentials();
  return envCreds.costFieldId;
}

export async function jiraRequest<T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  path: string,
  body?: Record<string, unknown>
): Promise<T> {
  const creds = getJiraCredentials();
  const auth = Buffer.from(`${creds.username}:${creds.apiToken}`).toString('base64');
  const url = `https://${creds.host}${path}`;

  const response = await fetch(url, {
    method,
    headers: {
      'Authorization': `Basic ${auth}`,
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Jira API error (${response.status}): ${error}`);
  }

  if (response.status === 204) {
    return { success: true } as T;
  }

  return response.json();
}

/**

/**
 * Upload a file as an attachment to a Jira issue.
 * Uses multipart/form-data with X-Atlassian-Token: no-check header
 * per Atlassian REST API requirements.
 */
export async function jiraUpload(issueKey: string, filePath: string, filename?: string): Promise<unknown> {
  const creds = getJiraCredentials();
  const auth = Buffer.from(`${creds.username}:${creds.apiToken}`).toString('base64');
  const url = `https://${creds.host}/rest/api/2/issue/${issueKey}/attachments`;

  const fileBuffer = await readFile(filePath);
  const resolvedFilename = filename || basename(filePath);

  const formData = new FormData();
  formData.append('file', new Blob([fileBuffer]), resolvedFilename);

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Authorization': `Basic ${auth}`,
      'X-Atlassian-Token': 'no-check',
    },
    body: formData,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Jira upload failed: ${response.status} ${text}`);
  }

  return response.json();
}

/**
 * Get default fields for a Jira skill when caller does not specify fields.
 *
 * Reads from ~/.claude/config/api-defaults.json with hardcoded fallbacks.
 * Returns a comma-separated string suitable for the Jira REST API fields parameter.
 */
export function getDefaultFields(skillName: string): string {
  const FALLBACKS: Record<string, string> = {
    search_issues: 'key,summary,status,priority,issuetype,assignee',
    get_issue: 'key,summary,status,priority,description,labels,components,issuetype,assignee',
    list_transitions: 'id,name,to',
  };

  try {
    const configPath = join(homedir(), '.claude', 'config', 'api-defaults.json');
    if (existsSync(configPath)) {
      const config = JSON.parse(readFileSync(configPath, 'utf-8'));
      const fieldValue = config?.jira?.[skillName]?.default_fields;
      if (typeof fieldValue === 'string' && fieldValue.length > 0) {
        return fieldValue;
      }
    }
  } catch {
    // Fall through to hardcoded defaults
  }

  return FALLBACKS[skillName] || '';
}

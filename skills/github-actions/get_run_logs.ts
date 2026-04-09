#!/usr/bin/env npx tsx
// get_run_logs - Get the download URL for a workflow run's logs.
// The GitHub API returns a 302 redirect to a short-lived zip URL.
// We follow the redirect and return the final URL so it can be
// downloaded externally (e.g. `curl -L <logs_url> -o logs.zip`).
import { getGitHubOwner } from './github-actions-client.js';
import { readFileSync, existsSync } from 'fs';
import { homedir } from 'os';
import { join } from 'path';

interface Input {
  owner?: string;
  repo: string;
  run_id: number;
}

/**
 * Resolve the GitHub token using the same 4-level credential chain
 * as github-actions-client.ts. We need direct access here because
 * we use fetch with redirect: 'manual' instead of ghActionsRequest.
 */
function resolveToken(): { token: string; apiUrl: string } {
  // 1. Env vars
  if (process.env.GITHUB_TOKEN) {
    return { token: process.env.GITHUB_TOKEN, apiUrl: process.env.GITHUB_API_URL || 'https://api.github.com' };
  }

  // 2. Project credentials
  const projectRoot = process.env.PROJECT_ROOT || process.cwd();
  const credsPath = join(projectRoot, '.claude', 'credentials.json');
  if (existsSync(credsPath)) {
    try {
      const raw = JSON.parse(readFileSync(credsPath, 'utf-8'));
      const creds = (raw.credentials ?? raw).github;
      if (creds?.token) return { token: creds.token, apiUrl: creds.apiUrl || 'https://api.github.com' };
    } catch { /* ignore */ }
  }

  // 3. .env file
  const envPath = join(projectRoot, '.env');
  if (existsSync(envPath)) {
    const content = readFileSync(envPath, 'utf-8');
    const match = content.match(/^GITHUB_TOKEN=(.+)$/m);
    if (match) {
      let val = match[1].trim();
      if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
        val = val.slice(1, -1);
      }
      const urlMatch = content.match(/^GITHUB_API_URL=(.+)$/m);
      let apiUrl = 'https://api.github.com';
      if (urlMatch) {
        apiUrl = urlMatch[1].trim().replace(/^["']|["']$/g, '');
      }
      return { token: val, apiUrl };
    }
  }

  // 4. ~/.claude/settings.json
  const settingsPath = join(homedir(), '.claude', 'settings.json');
  if (existsSync(settingsPath)) {
    try {
      const settings = JSON.parse(readFileSync(settingsPath, 'utf-8'));
      const creds = settings.credentials?.github;
      if (creds?.token) return { token: creds.token, apiUrl: creds.apiUrl || 'https://api.github.com' };
    } catch { /* ignore */ }
  }

  throw new Error('GitHub credentials not found for logs download');
}

async function execute(input: Input) {
  const owner = input.owner || getGitHubOwner();
  const { token, apiUrl } = resolveToken();
  const url = `${apiUrl}/repos/${owner}/${input.repo}/actions/runs/${input.run_id}/logs`;

  // Use redirect: 'manual' to capture the 302 Location header
  const response = await fetch(url, {
    method: 'GET',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    redirect: 'manual',
  });

  if (response.status === 302) {
    const logsUrl = response.headers.get('location');
    if (!logsUrl) throw new Error('Received 302 but no Location header');
    // The URL is a short-lived signed link to a zip archive.
    // Download it with: curl -L "<logs_url>" -o logs.zip
    return { run_id: input.run_id, logs_url: logsUrl };
  }

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`GitHub API error (${response.status}): ${error}`);
  }

  // Some configurations may return 200 with the zip body directly.
  // In that case, we can't easily extract a URL — report accordingly.
  return { run_id: input.run_id, logs_url: url };
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input)
  .then((r) => console.log(JSON.stringify(r, null, 2)))
  .catch((e) => { console.error(e.message); process.exit(1); });

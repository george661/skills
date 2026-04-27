#!/usr/bin/env npx tsx
/**
 * Issues Router — resolves issue-tracker provider (jira/github/linear) and
 * delegates to the right backend skill.
 *
 * Provider resolution order:
 * 1. Explicit `provider` argument
 * 2. ISSUE_TRACKER environment variable
 * 3. Default: jira
 *
 * Usage from other issues/ skills:
 *   import { resolveIssueProvider, translateParams, delegateIssue } from './issues-router.js';
 *   const provider = resolveIssueProvider();
 *   const result = delegateIssue(provider, 'get_issue', { issue_key: 'PROJ-1' });
 */
import { spawnSync } from 'child_process';
import { existsSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';

// ---------------------------------------------------------------------------
// Debug
// ---------------------------------------------------------------------------

const DEBUG = !!process.env.ISSUES_DEBUG;

function debug(...args: unknown[]) {
  if (DEBUG) process.stderr.write(`[issues-router] ${args.map(String).join(' ')}\n`);
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type IssueProvider = 'jira' | 'github' | 'linear';

// ---------------------------------------------------------------------------
// Skill name mapping — unified name → provider-specific name
// ---------------------------------------------------------------------------

const SKILL_NAME_MAP: Record<string, Partial<Record<IssueProvider, string>>> = {
  transition_issue: {
    github: 'update_issue_state',
    linear: 'update_issue_state',
  },
  list_transitions: {
    github: 'list_labels',
    linear: 'list_workflow_states',
  },
};

// ---------------------------------------------------------------------------
// Provider → skill directory mapping
// ---------------------------------------------------------------------------

const PROVIDER_SKILL_DIR: Record<IssueProvider, string> = {
  jira: 'jira',
  github: 'github-issues',
  linear: 'linear',
};

// ---------------------------------------------------------------------------
// resolveIssueProvider
// ---------------------------------------------------------------------------

/**
 * Resolve which issue-tracker provider to use.
 *
 * 1. Explicit argument (highest priority)
 * 2. ISSUE_TRACKER env var
 * 3. Default: jira
 */
export function resolveIssueProvider(explicit?: string): IssueProvider {
  debug('resolveIssueProvider called, explicit:', explicit);

  // 1. Explicit override
  if (explicit && isValidProvider(explicit)) {
    debug('resolved via explicit arg:', explicit);
    return explicit;
  }

  // 2. Environment variable
  const envVal = process.env.ISSUE_TRACKER;
  if (envVal && isValidProvider(envVal)) {
    debug('resolved via ISSUE_TRACKER env:', envVal);
    return envVal;
  }

  // 3. Default
  debug('resolved via default: jira');
  return 'jira';
}

function isValidProvider(value: string): value is IssueProvider {
  return value === 'jira' || value === 'github' || value === 'linear';
}

// ---------------------------------------------------------------------------
// translateParams
// ---------------------------------------------------------------------------

/**
 * Translate unified issue params to provider-specific params.
 *
 * - Jira: passthrough (native format)
 * - GitHub: parse `owner/repo#N` from issue_key, `owner/repo` from project_key
 * - Linear: map issue_key → identifier, project_key → teamKey
 */
export function translateParams(
  provider: IssueProvider,
  skill: string,
  params: Record<string, unknown>,
): Record<string, unknown> {
  debug('translateParams:', provider, skill, JSON.stringify(params));

  if (provider === 'jira') {
    // Jira is the native format — passthrough
    return { ...params };
  }

  if (provider === 'github') {
    return translateGitHubParams(skill, params);
  }

  if (provider === 'linear') {
    return translateLinearParams(skill, params);
  }

  // Fallback passthrough for unknown providers
  return { ...params };
}

function translateGitHubParams(
  _skill: string,
  params: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...params };

  // Parse issue_key: "owner/repo#123" → { owner, repo, issue_number }
  if (typeof out.issue_key === 'string') {
    const match = (out.issue_key as string).match(/^([^/]+)\/([^#]+)#(\d+)$/);
    if (match) {
      out.owner = match[1];
      out.repo = match[2];
      out.issue_number = parseInt(match[3], 10);
    }
    delete out.issue_key;
  }

  // Parse project_key: "owner/repo" → { owner, repo }
  if (typeof out.project_key === 'string') {
    const match = (out.project_key as string).match(/^([^/]+)\/(.+)$/);
    if (match) {
      out.owner = match[1];
      out.repo = match[2];
    }
    delete out.project_key;
  }

  return out;
}

export function translateLinearParams(
  skill: string,
  params: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...params };

  // Map issue_key → identifier
  if (typeof out.issue_key === 'string') {
    out.identifier = out.issue_key;
    delete out.issue_key;
  }

  // Map project_key → teamKey
  if (typeof out.project_key === 'string') {
    out.teamKey = out.project_key;
    delete out.project_key;
  }

  // For transition_issue: map transition_id → stateId, issue_key → identifier
  if (skill === 'transition_issue') {
    if (typeof out.transition_id === 'string') {
      out.stateId = out.transition_id;
      delete out.transition_id;
    }
    // Linear's update_issue_state will resolve identifier → id internally
  }

  // For search_issues: translate JQL to Linear IssueFilter if jql is provided
  if (skill === 'search_issues' && typeof out.jql === 'string') {
    const filter = translateJQLToLinearFilter(out.jql);
    out.filter = filter;
    delete out.jql;
  }

  return out;
}

/**
 * Translate a subset of JQL to Linear IssueFilter.
 * Supports:
 * - project = KEY
 * - status = "Status Name"
 * - Combined with AND
 *
 * Throws on unsupported JQL syntax.
 */
function translateJQLToLinearFilter(jql: string): Record<string, unknown> {
  const filter: Record<string, unknown> = {};
  const parts = jql.split(/\s+AND\s+/i);

  for (const part of parts) {
    const trimmed = part.trim();

    // Match: project = KEY or project = "KEY"
    const projectMatch = trimmed.match(/^project\s*=\s*"?([A-Z0-9-]+)"?$/i);
    if (projectMatch) {
      filter.team = { key: { eq: projectMatch[1] } };
      continue;
    }

    // Match: status = "Status Name" or status = StatusName
    const statusMatch = trimmed.match(/^status\s*=\s*"([^"]+)"$/i) || trimmed.match(/^status\s*=\s*([A-Za-z0-9\s]+)$/i);
    if (statusMatch) {
      filter.state = { name: { eq: statusMatch[1].trim() } };
      continue;
    }

    // Unsupported syntax
    throw new Error(`Unsupported JQL syntax in Linear translator: "${trimmed}". Supported: project = KEY, status = "Name", combined with AND.`);
  }

  return filter;
}

// ---------------------------------------------------------------------------
// delegateIssue
// ---------------------------------------------------------------------------

/**
 * Delegate to the appropriate provider skill.
 *
 * Resolves the skill directory, translates the skill name and params,
 * then spawns the provider skill via `npx tsx`.
 */
export function delegateIssue(
  provider: IssueProvider,
  skill: string,
  params: Record<string, unknown>,
): unknown {
  // Resolve provider-specific skill name
  const mappedSkill = SKILL_NAME_MAP[skill]?.[provider] ?? skill;
  const translatedParams = translateParams(provider, mappedSkill, params);

  // Resolve skill path
  const skillDir = join(homedir(), '.claude', 'skills', PROVIDER_SKILL_DIR[provider]);
  const skillPath = join(skillDir, `${mappedSkill}.ts`);

  if (!existsSync(skillPath)) {
    throw new Error(
      `Issue skill not found: ${skillPath} (provider: ${provider}, skill: ${mappedSkill})`,
    );
  }

  debug('delegateIssue:', provider, skill, '->', skillPath);
  debug('params:', JSON.stringify(translatedParams));

  // Use spawnSync to avoid shell escaping issues with JSON containing quotes
  const child = spawnSync('npx', ['tsx', skillPath, JSON.stringify(translatedParams)], {
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe'],
    timeout: 60000,
  });

  if (child.error) throw child.error;
  if (child.status !== 0) {
    const stderr = child.stderr?.trim() || '';
    throw new Error(stderr || `Issue skill '${mappedSkill}' exited with code ${child.status}`);
  }

  const result = child.stdout;
  try {
    return JSON.parse(result);
  } catch {
    return result; // plain text fallback
  }
}

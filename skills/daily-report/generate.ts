#!/usr/bin/env npx tsx
/**
 * daily-report/generate.ts
 *
 * Generates a daily work summary by collecting data from:
 *   - Git history across all repos in repositories.json
 *   - Jira issues updated since the last report
 *   - S3 deployment BOMs for dev, demo, and prod environments
 *   - E2E journey test results
 *
 * Output: $DAILY_REPORTS_PATH/YYYY-MM-DD.md
 *
 * Usage:
 *   npx tsx generate.ts [--force]
 */

import { execSync } from 'child_process';
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'fs';
import { homedir } from 'os';
import { join, resolve } from 'path';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

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
  } catch { /* ignore */ }
  return env;
}

function resolveProjectRoot(): string {
  if (process.env.PROJECT_ROOT) return resolve(process.env.PROJECT_ROOT);
  let dir = resolve(process.cwd());
  for (let i = 0; i < 10; i++) {
    if (existsSync(join(dir, '.env'))) return dir;
    const parent = resolve(dir, '..');
    if (parent === dir) break;
    dir = parent;
  }
  const home = homedir();
  for (const candidate of [join(home, 'projects', 'workspace'), join(home, 'workspace')]) {
    if (existsSync(join(candidate, '.env'))) return candidate;
  }
  return resolve(process.cwd());
}

const projectRoot = resolveProjectRoot();
const envPath = [
  join(projectRoot, 'agents', '.env'),
  join(projectRoot, '.env'),
].find(p => existsSync(p)) ?? '';
const envFile = envPath ? loadEnvFile(envPath) : {};

function env(key: string, fallback = ''): string {
  return process.env[key] ?? envFile[key] ?? fallback;
}

const DAILY_REPORTS_PATH = env('DAILY_REPORTS_PATH', join(projectRoot, 'daily-reports'));

function loadReposFromConfig(): string[] {
  // Resolution order:
  // 1. $PROJECT_ROOT/.claude/repositories.json (symlink placed by install.sh)
  // 2. Any $PROJECT_ROOT/*-agents/config/repositories.json
  // 3. Scan $PROJECT_ROOT/*/ for .git dirs (fallback)
  const candidates = [join(projectRoot, '.claude', 'repositories.json')];
  try {
    const entries = readdirSync(projectRoot, { withFileTypes: true });
    for (const e of entries) {
      if (e.isDirectory() && e.name.endsWith('-agents')) {
        candidates.push(join(projectRoot, e.name, 'config', 'repositories.json'));
      }
    }
  } catch { /* ignore */ }
  for (const p of candidates) {
    if (existsSync(p)) {
      try {
        const repos = JSON.parse(readFileSync(p, 'utf-8')) as Array<{ name: string }>;
        const names = repos.map(r => r.name).filter(Boolean);
        if (names.length > 0) return names;
      } catch { /* ignore */ }
    }
  }
  // Fallback: scan for .git dirs
  try {
    return readdirSync(projectRoot, { withFileTypes: true })
      .filter(e => e.isDirectory() && existsSync(join(projectRoot, e.name, '.git')))
      .map(e => e.name);
  } catch { return []; }
}

// repositories.json is primary; PROJECT_REPOS env var is fallback for legacy environments
const _reposFromConfig = loadReposFromConfig();
const PROJECT_REPOS = _reposFromConfig.length > 0
  ? _reposFromConfig
  : env('PROJECT_REPOS', '').split(',').map(r => r.trim()).filter(Boolean);
const AWS_PROFILE = env('PIPELINE_AWS_PROFILE', env('AWS_PROFILE', 'default'));
const BOM_BUCKET = env('PIPELINE_BUCKET', 'YOUR_PIPELINE_BUCKET');
const FORCE = process.argv.includes('--force');

// ---------------------------------------------------------------------------
// Time window
// ---------------------------------------------------------------------------

function findLastReportBoundary(): Date {
  if (!existsSync(DAILY_REPORTS_PATH)) {
    return new Date(Date.now() - 24 * 60 * 60 * 1000);
  }
  const reports = readdirSync(DAILY_REPORTS_PATH)
    .filter(f => f.match(/^\d{4}-\d{2}-\d{2}\.md$/))
    .sort()
    .reverse();

  if (reports.length === 0) {
    return new Date(Date.now() - 24 * 60 * 60 * 1000);
  }

  // Parse date from filename and set to 22:00 (10pm) on that day
  const [year, month, day] = reports[0].replace('.md', '').split('-').map(Number);
  const boundary = new Date(year, month - 1, day, 22, 0, 0, 0);
  // If boundary is in the future (e.g. running before 10pm on same day), subtract 24h
  if (boundary > new Date()) {
    boundary.setDate(boundary.getDate() - 1);
  }
  return boundary;
}

// ---------------------------------------------------------------------------
// Git history
// ---------------------------------------------------------------------------

interface CommitGroup {
  repo: string;
  commits: string[];
}

function collectGitHistory(boundary: Date): CommitGroup[] {
  let authorEmail = '';
  try {
    authorEmail = execSync('git config user.email', { encoding: 'utf-8' }).trim();
  } catch { /* no global git config */ }

  const since = boundary.toISOString();
  const groups: CommitGroup[] = [];

  for (const repo of PROJECT_REPOS) {
    const repoPath = join(projectRoot, repo);
    if (!existsSync(repoPath)) continue;

    try {
      const args = [
        '-C', repoPath,
        'log',
        `--since=${since}`,
        '--oneline',
        '--no-merges',
      ];
      if (authorEmail) args.push(`--author=${authorEmail}`);

      const output = execSync(`git ${args.join(' ')}`, { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'ignore'] }).trim();
      const commits = output ? output.split('\n').filter(Boolean) : [];
      if (commits.length > 0) {
        groups.push({ repo, commits });
      }
    } catch { /* repo may not have commits or git may fail */ }
  }

  return groups;
}

// ---------------------------------------------------------------------------
// Jira
// ---------------------------------------------------------------------------

interface JiraIssue {
  key: string;
  summary: string;
  status: string;
  labels: string[];
}

function collectJiraIssues(boundary: Date): JiraIssue[] {
  const sinceStr = boundary.toISOString().split('T')[0]; // YYYY-MM-DD
  const jql = `project = ${PROJECT_KEY} AND updated >= "${sinceStr}" ORDER BY updated DESC`;
  const fields = ['key', 'summary', 'status', 'labels'];

  try {
    const skillPath = join(projectRoot, '.claude', 'skills', 'jira', 'search_issues.ts');
    const fallbackSkillPath = join(homedir(), '.claude', 'skills', 'jira', 'search_issues.ts');
    const skill = existsSync(skillPath) ? skillPath : fallbackSkillPath;

    if (!existsSync(skill)) return [];

    const input = JSON.stringify({ jql, fields, max_results: 50 });
    const result = execSync(`npx tsx "${skill}" '${input}'`, {
      encoding: 'utf-8',
      env: { ...process.env, PROJECT_ROOT: projectRoot },
      cwd: projectRoot,
    });

    const parsed = JSON.parse(result);
    const issues: JiraIssue[] = (parsed.issues || []).map((i: Record<string, unknown>) => {
      const f = (i.fields ?? {}) as Record<string, unknown>;
      const statusObj = f.status as Record<string, unknown> | undefined;
      const labelsArr = f.labels as string[] | undefined;
      return {
        key: i.key as string,
        summary: (f.summary as string) ?? '',
        status: (statusObj?.name as string) ?? '',
        labels: labelsArr ?? [],
      };
    });
    return issues;
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// S3 BOMs
// ---------------------------------------------------------------------------

interface BomEntry {
  repo: string;
  env: string;
  version?: string;
  timestamp?: string;
}

function fetchBom(repo: string, environment: string): BomEntry {
  const s3Path = `s3://${BOM_BUCKET}/deployments/${repo}/${environment}/latest.json`;
  try {
    const result = execSync(
      `aws s3 cp "${s3Path}" - --profile ${AWS_PROFILE}`,
      { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'ignore'] }
    );
    const data = JSON.parse(result) as Record<string, unknown>;
    return {
      repo,
      env: environment,
      version: (data.version as string) || (data.tag as string) || (data.commit as string),
      timestamp: (data.timestamp as string) || (data.deployed_at as string),
    };
  } catch {
    return { repo, env: environment };
  }
}

function listDeployedRepos(): string[] {
  try {
    const output = execSync(
      `aws s3 ls s3://${BOM_BUCKET}/deployments/ --profile ${AWS_PROFILE}`,
      { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'ignore'] }
    );
    return output
      .split('\n')
      .map(l => l.match(/PRE (.+)\//)?.[1] ?? '')
      .filter(Boolean);
  } catch {
    return PROJECT_REPOS;
  }
}

async function collectBoms(boundary: Date): Promise<BomEntry[]> {
  const environments = ['dev', 'demo', 'prod'];
  const repos = listDeployedRepos();
  const tasks: Promise<BomEntry>[] = [];

  for (const repo of repos) {
    for (const environment of environments) {
      tasks.push(Promise.resolve(fetchBom(repo, environment)));
    }
  }

  const results = await Promise.all(tasks);
  // Filter to only entries that have data and were deployed after the boundary
  return results.filter(b => {
    if (!b.version && !b.timestamp) return false;
    if (b.timestamp) {
      try {
        return new Date(b.timestamp) >= boundary;
      } catch { return true; }
    }
    return true;
  });
}

// ---------------------------------------------------------------------------
// E2E report
// ---------------------------------------------------------------------------

interface E2EReport {
  domains: Array<{ name: string; passed: number; failed: number; total: number }>;
  reportUrl?: string;
}

function collectE2EReport(): E2EReport | null {
  const s3Path = `s3://${BOM_BUCKET}/e2e-reports/journey-tests/latest.json`;
  try {
    const result = execSync(
      `aws s3 cp "${s3Path}" - --profile ${AWS_PROFILE}`,
      { encoding: 'utf-8', stdio: ['pipe', 'pipe', 'ignore'] }
    );
    const data = JSON.parse(result) as Record<string, unknown>;
    // domains is an object: { domainName: { passed, failed, skipped } }
    const domainsRaw = data.domains as Record<string, Record<string, number>> | undefined;
    const domains = domainsRaw
      ? Object.entries(domainsRaw).map(([name, stats]) => ({
          name,
          passed: stats.passed ?? 0,
          failed: stats.failed ?? 0,
          total: (stats.passed ?? 0) + (stats.failed ?? 0) + (stats.skipped ?? 0),
        }))
      : [];
    return { domains, reportUrl: data.reportUrl as string | undefined };
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Report generation
// ---------------------------------------------------------------------------

function formatPeriod(boundary: Date, now: Date): string {
  const fmt = (d: Date) =>
    d.toLocaleString('en-US', {
      timeZone: env('DAILY_REPORTS_TIMEZONE', 'America/New_York'),
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
  return `${fmt(boundary)} → ${fmt(now)}`;
}

function buildReport(
  now: Date,
  boundary: Date,
  gitGroups: CommitGroup[],
  jiraIssues: JiraIssue[],
  boms: BomEntry[],
  e2e: E2EReport | null,
): string {
  const dateStr = now.toLocaleDateString('en-CA', {
    timeZone: env('DAILY_REPORTS_TIMEZONE', 'America/New_York'),
  }); // YYYY-MM-DD

  const lines: string[] = [
    `# Daily Report — ${dateStr}`,
    '',
    `> Period: ${formatPeriod(boundary, now)}`,
    '',
  ];

  // --- Accomplished ---
  lines.push('## Accomplished', '');

  const closedStatuses = new Set(['Done', 'Closed', 'Resolved', 'Validation']);
  const closedIssues = jiraIssues.filter(i => closedStatuses.has(i.status));

  if (gitGroups.length === 0 && closedIssues.length === 0) {
    lines.push('_No commits or closed issues in this period._', '');
  } else {
    for (const group of gitGroups) {
      const truncated = group.commits.slice(0, 5);
      const overflow = group.commits.length - truncated.length;
      const commitList = truncated.map(c => `"${c.replace(/^[a-f0-9]+ /, '')}"`).join(', ');
      lines.push(`- **${group.repo}** — ${group.commits.length} commit${group.commits.length !== 1 ? 's' : ''}: ${commitList}${overflow > 0 ? ` (+${overflow} more)` : ''}`);
    }
    if (closedIssues.length > 0) {
      const issueList = closedIssues.map(i => `${i.key} (${i.status})`).join(', ');
      lines.push(`- **Jira closed** — ${issueList}`);
    }
    lines.push('');
  }

  // --- Deployments ---
  lines.push('## Deployments', '');

  const envOrder = ['dev', 'demo', 'prod'];
  const bomByRepo: Record<string, Record<string, string>> = {};
  for (const b of boms) {
    if (!bomByRepo[b.repo]) bomByRepo[b.repo] = {};
    bomByRepo[b.repo][b.env] = b.version ?? '—';
  }

  const deployedRepos = Object.keys(bomByRepo);
  if (deployedRepos.length === 0) {
    lines.push('_No deployment BOMs found for this period._', '');
  } else {
    lines.push('| Repo | Dev | Demo | Prod |');
    lines.push('|------|-----|------|------|');
    for (const repo of deployedRepos) {
      const row = envOrder.map(e => bomByRepo[repo][e] ?? '—');
      lines.push(`| ${repo} | ${row.join(' | ')} |`);
    }
    lines.push('');
  }

  // --- E2E Tests ---
  lines.push('## E2E Tests', '');
  if (!e2e) {
    lines.push('_E2E report unavailable._', '');
  } else {
    const totalFailed = e2e.domains.filter(d => d.failed > 0);
    const total = e2e.domains.length;
    const passing = e2e.domains.filter(d => d.failed === 0).length;
    const reportLink = e2e.reportUrl ? ` | [View Report](${e2e.reportUrl})` : '';
    lines.push(`- ${passing}/${total} domains passing | ${totalFailed.length} failing${totalFailed.length > 0 ? ': ' + totalFailed.map(d => `\`${d.name}\``).join(', ') : ''}${reportLink}`);
    lines.push('');
  }

  // --- In Progress ---
  const stepLabels = [
    'step:implementing', 'step:awaiting-ci', 'step:ready-for-review',
    'step:reviewing', 'step:fixing-pr', 'step:validating',
  ];
  const inProgress = jiraIssues.filter(
    i => !closedStatuses.has(i.status) && i.labels.some(l => stepLabels.includes(l))
  );

  lines.push('## In Progress', '');
  if (inProgress.length === 0) {
    lines.push('_No issues currently in an active workflow step._', '');
  } else {
    for (const issue of inProgress) {
      const stepLabel = issue.labels.find(l => l.startsWith('step:')) ?? '';
      lines.push(`- ${issue.key} \`${stepLabel}\` — ${issue.summary}`);
    }
    lines.push('');
  }

  // --- Next / Incomplete ---
  lines.push('## Next / Incomplete', '');

  const incomplete: string[] = [];

  // Issues still open with no active step (To Do / backlog)
  const openNoStep = jiraIssues.filter(
    i => !closedStatuses.has(i.status) && !i.labels.some(l => l.startsWith('step:'))
  );
  for (const issue of openNoStep) {
    incomplete.push(`- [ ] ${issue.key} — ${issue.summary} _(${issue.status})_`);
  }

  // In-progress issues needing follow-up
  for (const issue of inProgress) {
    const stepLabel = issue.labels.find(l => l.startsWith('step:')) ?? '';
    const action = stepLabel === 'step:awaiting-ci' ? 'review after CI green'
      : stepLabel === 'step:ready-for-review' ? 'run /review'
      : stepLabel === 'step:reviewing' ? 'awaiting review approval'
      : stepLabel === 'step:fixing-pr' ? 'fix PR and re-push'
      : stepLabel === 'step:validating' ? 'complete validation'
      : 'continue work';
    incomplete.push(`- [ ] ${issue.key} — ${action}`);
  }

  // Failing E2E domains
  if (e2e) {
    for (const domain of e2e.domains.filter(d => d.failed > 0)) {
      incomplete.push(`- [ ] E2E \`${domain.name}\` — ${domain.failed}/${domain.total} tests failing`);
    }
  }

  if (incomplete.length === 0) {
    lines.push('_Nothing incomplete — great day!_', '');
  } else {
    lines.push(...incomplete, '');
  }

  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const now = new Date();
  const boundary = findLastReportBoundary();

  const dateStr = now.toLocaleDateString('en-CA', {
    timeZone: env('DAILY_REPORTS_TIMEZONE', 'America/New_York'),
  });
  const outPath = join(DAILY_REPORTS_PATH, `${dateStr}.md`);

  if (existsSync(outPath) && !FORCE) {
    console.log(`Report already exists: ${outPath}`);
    console.log('Use --force to overwrite.');
    process.exit(0);
  }

  mkdirSync(DAILY_REPORTS_PATH, { recursive: true });

  console.log(`Generating daily report for ${dateStr}...`);
  console.log(`Period: since ${boundary.toISOString()}`);

  const [gitGroups, jiraIssues, boms, e2e] = await Promise.all([
    Promise.resolve(collectGitHistory(boundary)),
    Promise.resolve(collectJiraIssues(boundary)),
    collectBoms(boundary),
    Promise.resolve(collectE2EReport()),
  ]);

  console.log(`  git: ${gitGroups.length} repos with commits`);
  console.log(`  jira: ${jiraIssues.length} issues`);
  console.log(`  boms: ${boms.length} deployment entries`);
  console.log(`  e2e: ${e2e ? e2e.domains.length + ' domains' : 'unavailable'}`);

  const report = buildReport(now, boundary, gitGroups, jiraIssues, boms, e2e);
  writeFileSync(outPath, report, 'utf-8');

  console.log(`\nReport written to: ${outPath}`);
}

main().catch(e => {
  console.error('Error generating report:', e instanceof Error ? e.message : String(e));
  process.exit(1);
});

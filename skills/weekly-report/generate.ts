#!/usr/bin/env npx tsx
/**
 * weekly-report/generate.ts
 *
 * Generates a weekly work summary by:
 *   Phase 1 — Fresh analysis: git history + Jira issues for the ISO week window
 *   Phase 2 — Cross-check: read existing daily-report files and incorporate them
 *
 * Output: $DAILY_REPORTS_PATH/YYYY-WW.md
 *
 * Usage:
 *   npx tsx generate.ts                   # current ISO week
 *   npx tsx generate.ts --week=2026-W13   # specific ISO week
 *   npx tsx generate.ts --force            # overwrite existing
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
const FORCE = process.argv.includes('--force');

function loadReposFromConfig(): string[] {
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
  try {
    return readdirSync(projectRoot, { withFileTypes: true })
      .filter(e => e.isDirectory() && existsSync(join(projectRoot, e.name, '.git')))
      .map(e => e.name);
  } catch { return []; }
}

const _reposFromConfig = loadReposFromConfig();
const REPOS = _reposFromConfig.length > 0
  ? _reposFromConfig
  : env('PROJECT_REPOS', '').split(',').map(r => r.trim()).filter(Boolean);

// ---------------------------------------------------------------------------
// ISO week utilities
// ---------------------------------------------------------------------------

/**
 * Returns {year, week, start, end} for a given ISO week.
 * start = Monday 00:00:00, end = Sunday 23:59:59 (local time).
 */
function resolveWeek(weekArg?: string): { label: string; start: Date; end: Date } {
  let year: number;
  let week: number;

  if (weekArg) {
    const m = weekArg.match(/^(\d{4})-W(\d{1,2})$/);
    if (!m) {
      console.error(`Invalid week format: ${weekArg}. Expected YYYY-WNN (e.g. 2026-W13)`);
      process.exit(1);
    }
    year = parseInt(m[1]);
    week = parseInt(m[2]);
  } else {
    const now = new Date();
    // ISO week: week 1 = week containing the first Thursday
    const jan4 = new Date(now.getFullYear(), 0, 4);
    const startOfYear = new Date(jan4);
    startOfYear.setDate(jan4.getDate() - ((jan4.getDay() + 6) % 7)); // Monday of week 1

    const daysSinceWeek1 = Math.floor((now.getTime() - startOfYear.getTime()) / 86400000);
    week = Math.floor(daysSinceWeek1 / 7) + 1;
    year = now.getFullYear();

    // Handle year boundary: if week 0, it belongs to last year
    if (week <= 0) {
      year -= 1;
      week = isoWeeksInYear(year);
    }
    // If week > 52/53, it may belong to next year
    if (week > isoWeeksInYear(year)) {
      year += 1;
      week = 1;
    }
  }

  // Monday of the given ISO week
  const jan4 = new Date(year, 0, 4);
  const mondayW1 = new Date(jan4);
  mondayW1.setDate(jan4.getDate() - ((jan4.getDay() + 6) % 7));

  const start = new Date(mondayW1);
  start.setDate(mondayW1.getDate() + (week - 1) * 7);
  start.setHours(0, 0, 0, 0);

  const end = new Date(start);
  end.setDate(start.getDate() + 6);
  end.setHours(23, 59, 59, 999);

  const label = `${year}-W${String(week).padStart(2, '0')}`;
  return { label, start, end };
}

function isoWeeksInYear(year: number): number {
  // A year has 53 ISO weeks if Jan 1 or Dec 31 is Thursday
  const jan1Day = new Date(year, 0, 1).getDay();
  const dec31Day = new Date(year, 11, 31).getDay();
  return jan1Day === 4 || dec31Day === 4 ? 53 : 52;
}

// ---------------------------------------------------------------------------
// Phase 1: Fresh git analysis
// ---------------------------------------------------------------------------

interface CommitGroup {
  repo: string;
  commits: string[];
}

function collectGitHistory(start: Date, end: Date): CommitGroup[] {
  let authorEmail = '';
  try {
    authorEmail = execSync('git config user.email', { encoding: 'utf-8' }).trim();
  } catch { /* no global git config */ }

  const since = start.toISOString();
  const until = end.toISOString();
  const groups: CommitGroup[] = [];

  for (const repo of REPOS) {
    const repoPath = join(projectRoot, repo);
    if (!existsSync(repoPath)) continue;
    try {
      const args = ['-C', repoPath, 'log', `--since=${since}`, `--until=${until}`, '--oneline', '--no-merges'];
      if (authorEmail) args.push(`--author=${authorEmail}`);
      const output = execSync(`git ${args.join(' ')}`, {
        encoding: 'utf-8', stdio: ['pipe', 'pipe', 'ignore'],
      }).trim();
      const commits = output ? output.split('\n').filter(Boolean) : [];
      if (commits.length > 0) groups.push({ repo, commits });
    } catch { /* skip */ }
  }

  return groups;
}

// ---------------------------------------------------------------------------
// Phase 1: Fresh Jira analysis
// ---------------------------------------------------------------------------

interface JiraIssue {
  key: string;
  summary: string;
  status: string;
  labels: string[];
}

function collectJiraIssues(start: Date, end: Date): JiraIssue[] {
  const sinceStr = start.toISOString().split('T')[0];
  const untilStr = end.toISOString().split('T')[0];
  const jql = `project = ${PROJECT_KEY} AND updated >= "${sinceStr}" AND updated <= "${untilStr}" ORDER BY updated DESC`;
  const fields = ['key', 'summary', 'status', 'labels'];

  try {
    const skillPath = join(projectRoot, '.claude', 'skills', 'jira', 'search_issues.ts');
    const fallbackSkillPath = join(homedir(), '.claude', 'skills', 'jira', 'search_issues.ts');
    const skill = existsSync(skillPath) ? skillPath : fallbackSkillPath;
    if (!existsSync(skill)) return [];

    const input = JSON.stringify({ jql, fields, max_results: 100 });
    const result = execSync(`npx tsx "${skill}" '${input}'`, {
      encoding: 'utf-8',
      env: { ...process.env, PROJECT_ROOT: projectRoot },
      cwd: projectRoot,
    });

    const parsed = JSON.parse(result);
    return (parsed.issues || []).map((i: Record<string, unknown>) => {
      const f = (i.fields ?? {}) as Record<string, unknown>;
      return {
        key: i.key as string,
        summary: (f.summary as string) ?? '',
        status: ((f.status as Record<string, unknown>)?.name as string) ?? '',
        labels: (f.labels as string[]) ?? [],
      };
    });
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// Phase 2: Read existing daily reports
// ---------------------------------------------------------------------------

interface DailyReportSummary {
  date: string;
  accomplished: string[];
  inProgress: string[];
  incomplete: string[];
}

function readDailyReports(start: Date, end: Date): DailyReportSummary[] {
  if (!existsSync(DAILY_REPORTS_PATH)) return [];

  const summaries: DailyReportSummary[] = [];
  const files = readdirSync(DAILY_REPORTS_PATH)
    .filter(f => f.match(/^\d{4}-\d{2}-\d{2}\.md$/))
    .sort();

  for (const file of files) {
    const [year, month, day] = file.replace('.md', '').split('-').map(Number);
    const fileDate = new Date(year, month - 1, day);
    if (fileDate < start || fileDate > end) continue;

    try {
      const content = readFileSync(join(DAILY_REPORTS_PATH, file), 'utf-8');
      const summary = parseDailyReport(file.replace('.md', ''), content);
      summaries.push(summary);
    } catch { /* skip unreadable files */ }
  }

  return summaries;
}

function parseDailyReport(date: string, content: string): DailyReportSummary {
  const lines = content.split('\n');
  const accomplished: string[] = [];
  const inProgress: string[] = [];
  const incomplete: string[] = [];

  let section = '';
  for (const line of lines) {
    if (line.startsWith('## Accomplished')) { section = 'accomplished'; continue; }
    if (line.startsWith('## In Progress')) { section = 'inProgress'; continue; }
    if (line.startsWith('## Next / Incomplete')) { section = 'incomplete'; continue; }
    if (line.startsWith('## ')) { section = ''; continue; }

    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('>') || trimmed.startsWith('_')) continue;

    if (section === 'accomplished' && trimmed.startsWith('-')) {
      accomplished.push(trimmed.slice(1).trim());
    } else if (section === 'inProgress' && trimmed.startsWith('-')) {
      inProgress.push(trimmed.slice(1).trim());
    } else if (section === 'incomplete' && trimmed.startsWith('- [')) {
      incomplete.push(trimmed.replace(/^- \[.\] /, ''));
    }
  }

  return { date, accomplished, inProgress, incomplete };
}

// ---------------------------------------------------------------------------
// Report generation
// ---------------------------------------------------------------------------

function buildReport(
  weekLabel: string,
  start: Date,
  end: Date,
  gitGroups: CommitGroup[],
  jiraIssues: JiraIssue[],
  dailies: DailyReportSummary[],
): string {
  const tz = env('DAILY_REPORTS_TIMEZONE', 'America/New_York');
  const fmt = (d: Date) => d.toLocaleDateString('en-CA', { timeZone: tz });
  const lines: string[] = [
    `# Weekly Report — ${weekLabel}`,
    '',
    `> Period: ${fmt(start)} → ${fmt(end)}`,
    '',
  ];

  // --- Summary stats ---
  const totalCommits = gitGroups.reduce((n, g) => n + g.commits.length, 0);
  const closedStatuses = new Set(['Done', 'Closed', 'Resolved', 'Validation']);
  const closed = jiraIssues.filter(i => closedStatuses.has(i.status));
  const daysWithReports = dailies.length;

  lines.push('## Summary', '');
  lines.push(`- ${totalCommits} commit${totalCommits !== 1 ? 's' : ''} across ${gitGroups.length} repo${gitGroups.length !== 1 ? 's' : ''}`);
  lines.push(`- ${closed.length} issue${closed.length !== 1 ? 's' : ''} closed`);
  lines.push(`- ${daysWithReports} of 5 work day${daysWithReports !== 1 ? 's' : ''} with reports`);
  lines.push('');

  // --- Accomplished (from git + closed issues) ---
  lines.push('## Accomplished', '');

  if (gitGroups.length === 0 && closed.length === 0 && dailies.length === 0) {
    lines.push('_No commits, closed issues, or daily reports for this week._', '');
  } else {
    for (const group of gitGroups) {
      lines.push(`**${group.repo}** (${group.commits.length} commit${group.commits.length !== 1 ? 's' : ''})`);
      for (const c of group.commits.slice(0, 8)) {
        lines.push(`- ${c.replace(/^[a-f0-9]+ /, '')}`);
      }
      if (group.commits.length > 8) {
        lines.push(`- _(+${group.commits.length - 8} more)_`);
      }
      lines.push('');
    }

    if (closed.length > 0) {
      lines.push('**Closed Issues**');
      for (const issue of closed) {
        lines.push(`- ${issue.key} — ${issue.summary}`);
      }
      lines.push('');
    }
  }

  // --- Daily highlights (Phase 2 cross-check) ---
  if (dailies.length > 0) {
    lines.push('## Daily Highlights', '');
    for (const day of dailies) {
      if (day.accomplished.length === 0) continue;
      lines.push(`**${day.date}**`);
      for (const item of day.accomplished.slice(0, 3)) {
        lines.push(`- ${item}`);
      }
      if (day.accomplished.length > 3) {
        lines.push(`- _(+${day.accomplished.length - 3} more)_`);
      }
      lines.push('');
    }
  }

  // --- In Progress ---
  const stepLabels = ['step:implementing', 'step:awaiting-ci', 'step:ready-for-review', 'step:reviewing', 'step:fixing-pr'];
  const inProgress = jiraIssues.filter(
    i => !closedStatuses.has(i.status) && i.labels.some(l => stepLabels.includes(l))
  );

  lines.push('## In Progress', '');
  if (inProgress.length === 0) {
    lines.push('_No issues in an active workflow step._', '');
  } else {
    for (const issue of inProgress) {
      const step = issue.labels.find(l => l.startsWith('step:')) ?? '';
      lines.push(`- ${issue.key} \`${step}\` — ${issue.summary}`);
    }
    lines.push('');
  }

  // --- Carryover / Incomplete (aggregate from dailies) ---
  const allIncomplete = new Map<string, string>();
  for (const day of dailies) {
    for (const item of day.incomplete) {
      // Deduplicate by issue key if detectable
      const key = item.match(/^(PROJ-\d+)/)?.[1] ?? item.slice(0, 60);
      allIncomplete.set(key, item);
    }
  }

  lines.push('## Carryover', '');
  if (allIncomplete.size === 0) {
    lines.push('_Nothing carried over from daily reports._', '');
  } else {
    for (const item of allIncomplete.values()) {
      lines.push(`- [ ] ${item}`);
    }
    lines.push('');
  }

  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const weekArg = process.argv.find(a => a.startsWith('--week='))?.replace('--week=', '');
  const { label, start, end } = resolveWeek(weekArg);

  const outPath = join(DAILY_REPORTS_PATH, `${label}.md`);

  if (existsSync(outPath) && !FORCE) {
    console.log(`Report already exists: ${outPath}`);
    console.log('Use --force to overwrite.');
    process.exit(0);
  }

  mkdirSync(DAILY_REPORTS_PATH, { recursive: true });

  console.log(`Generating weekly report for ${label}...`);
  console.log(`Period: ${start.toISOString().split('T')[0]} → ${end.toISOString().split('T')[0]}`);

  console.log('Phase 1: fresh analysis...');
  const [gitGroups, jiraIssues] = await Promise.all([
    Promise.resolve(collectGitHistory(start, end)),
    Promise.resolve(collectJiraIssues(start, end)),
  ]);

  console.log('Phase 2: cross-checking daily reports...');
  const dailies = readDailyReports(start, end);

  console.log(`  git: ${gitGroups.length} repos with commits`);
  console.log(`  jira: ${jiraIssues.length} issues`);
  console.log(`  daily reports: ${dailies.length} files`);

  const report = buildReport(label, start, end, gitGroups, jiraIssues, dailies);
  writeFileSync(outPath, report, 'utf-8');
  console.log(`\nReport written to: ${outPath}`);
}

main().catch(e => {
  console.error('Error generating weekly report:', e instanceof Error ? e.message : String(e));
  process.exit(1);
});

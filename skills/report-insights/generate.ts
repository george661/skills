#!/usr/bin/env npx tsx
/**
 * report-insights/generate.ts
 *
 * Correlates loop-metrics data (Claude Code session JSONL files) with
 * daily/weekly reports to surface patterns and insights.
 *
 * Output: $DAILY_REPORTS_PATH/insights/YYYY-WW.md
 *
 * Usage:
 *   npx tsx generate.ts                   # current ISO week
 *   npx tsx generate.ts --week=2026-W13   # specific ISO week
 *   npx tsx generate.ts --force            # overwrite existing
 */

import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'fs';
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
const INSIGHTS_PATH = join(DAILY_REPORTS_PATH, 'insights');
const FORCE = process.argv.includes('--force');

// ---------------------------------------------------------------------------
// ISO week utilities
// ---------------------------------------------------------------------------

function isoWeeksInYear(year: number): number {
  const jan1Day = new Date(year, 0, 1).getDay();
  const dec31Day = new Date(year, 11, 31).getDay();
  return jan1Day === 4 || dec31Day === 4 ? 53 : 52;
}

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
    const jan4 = new Date(now.getFullYear(), 0, 4);
    const startOfYear = new Date(jan4);
    startOfYear.setDate(jan4.getDate() - ((jan4.getDay() + 6) % 7));
    const daysSinceWeek1 = Math.floor((now.getTime() - startOfYear.getTime()) / 86400000);
    week = Math.floor(daysSinceWeek1 / 7) + 1;
    year = now.getFullYear();
    if (week <= 0) { year -= 1; week = isoWeeksInYear(year); }
    if (week > isoWeeksInYear(year)) { year += 1; week = 1; }
  }

  const jan4 = new Date(year, 0, 4);
  const mondayW1 = new Date(jan4);
  mondayW1.setDate(jan4.getDate() - ((jan4.getDay() + 6) % 7));

  const start = new Date(mondayW1);
  start.setDate(mondayW1.getDate() + (week - 1) * 7);
  start.setHours(0, 0, 0, 0);

  const end = new Date(start);
  end.setDate(start.getDate() + 6);
  end.setHours(23, 59, 59, 999);

  return { label: `${year}-W${String(week).padStart(2, '0')}`, start, end };
}

// ---------------------------------------------------------------------------
// Session JSONL parsing
// ---------------------------------------------------------------------------

interface SessionEvent {
  type: string;
  timestamp?: string;
  message?: Record<string, unknown>;
  toolUseId?: string;
  toolName?: string;
  costUSD?: number;
  durationMs?: number;
}

interface SessionStats {
  sessionId: string;
  projectPath: string;
  date: string;
  totalEvents: number;
  toolUseCounts: Record<string, number>;
  commandCounts: Record<string, number>;
  totalCostUSD: number;
  totalDurationMs: number;
  errorCount: number;
  linesOfContext: number;
}

function parseSessionFile(filePath: string): SessionStats | null {
  try {
    const content = readFileSync(filePath, 'utf-8');
    const lines = content.split('\n').filter(Boolean);

    const stats: SessionStats = {
      sessionId: filePath.split('/').pop()?.replace('.jsonl', '') ?? '',
      projectPath: '',
      date: '',
      totalEvents: 0,
      toolUseCounts: {},
      commandCounts: {},
      totalCostUSD: 0,
      totalDurationMs: 0,
      errorCount: 0,
      linesOfContext: lines.length,
    };

    let firstTs = '';
    for (const line of lines) {
      try {
        const event = JSON.parse(line) as SessionEvent;
        stats.totalEvents++;

        if (!firstTs && event.timestamp) {
          firstTs = event.timestamp;
          stats.date = event.timestamp.split('T')[0];
        }

        if (event.type === 'tool_use' && event.toolName) {
          stats.toolUseCounts[event.toolName] = (stats.toolUseCounts[event.toolName] ?? 0) + 1;
        }

        if (event.type === 'tool_result' || event.type === 'tool_use') {
          if (event.costUSD) stats.totalCostUSD += event.costUSD;
          if (event.durationMs) stats.totalDurationMs += event.durationMs;
        }

        // Detect slash command invocations from Skill tool calls
        const msg = event.message;
        if (msg && typeof msg === 'object') {
          const content = (msg as Record<string, unknown>).content;
          if (Array.isArray(content)) {
            for (const part of content) {
              if (part && typeof part === 'object') {
                const p = part as Record<string, unknown>;
                if (p.type === 'tool_use' && p.name === 'Skill') {
                  const inp = p.input as Record<string, unknown> | undefined;
                  const skillName = inp?.name as string | undefined;
                  if (skillName) {
                    stats.commandCounts[skillName] = (stats.commandCounts[skillName] ?? 0) + 1;
                  }
                }
              }
            }
          }
        }

        if (event.type === 'tool_result') {
          const result = (event as unknown as Record<string, unknown>).content;
          if (typeof result === 'string' && result.toLowerCase().includes('error')) {
            stats.errorCount++;
          }
        }
      } catch { /* skip malformed lines */ }
    }

    return stats;
  } catch {
    return null;
  }
}

function collectSessionStats(start: Date, end: Date): SessionStats[] {
  const projectsDir = join(homedir(), '.claude', 'projects');
  if (!existsSync(projectsDir)) return [];

  const allStats: SessionStats[] = [];

  function scanDir(dir: string): void {
    if (!existsSync(dir)) return;
    const entries = readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = join(dir, entry.name);
      if (entry.isDirectory()) {
        scanDir(fullPath);
      } else if (entry.name.endsWith('.jsonl')) {
        const mtime = statSync(fullPath).mtime;
        if (mtime >= start && mtime <= end) {
          const stats = parseSessionFile(fullPath);
          if (stats) allStats.push(stats);
        }
      }
    }
  }

  scanDir(projectsDir);
  return allStats;
}

// ---------------------------------------------------------------------------
// Daily report reading (for correlation)
// ---------------------------------------------------------------------------

interface DailySnapshot {
  date: string;
  commitCount: number;
  closedCount: number;
  incompleteCount: number;
}

function readDailySnapshots(start: Date, end: Date): DailySnapshot[] {
  if (!existsSync(DAILY_REPORTS_PATH)) return [];
  const snapshots: DailySnapshot[] = [];

  for (const file of readdirSync(DAILY_REPORTS_PATH).filter(f => f.match(/^\d{4}-\d{2}-\d{2}\.md$/)).sort()) {
    const [year, month, day] = file.replace('.md', '').split('-').map(Number);
    const fileDate = new Date(year, month - 1, day);
    if (fileDate < start || fileDate > end) continue;

    try {
      const content = readFileSync(join(DAILY_REPORTS_PATH, file), 'utf-8');
      const commitMatch = content.match(/(\d+) commit/);
      const closedMatch = content.match(/Jira closed.*?([A-Z]+-\d+)/g);
      const incompleteMatch = content.match(/^- \[ \]/gm);

      snapshots.push({
        date: file.replace('.md', ''),
        commitCount: commitMatch ? parseInt(commitMatch[1]) : 0,
        closedCount: closedMatch ? closedMatch.length : 0,
        incompleteCount: incompleteMatch ? incompleteMatch.length : 0,
      });
    } catch { /* skip */ }
  }

  return snapshots;
}

// ---------------------------------------------------------------------------
// Insight derivation
// ---------------------------------------------------------------------------

interface Insights {
  topTools: Array<{ name: string; count: number }>;
  topCommands: Array<{ name: string; count: number }>;
  totalSessions: number;
  totalEvents: number;
  totalCostUSD: number;
  estimatedHours: number;
  avgEventsPerSession: number;
  busyDays: Array<{ date: string; sessions: number }>;
  correlations: string[];
  anomalies: string[];
}

function deriveInsights(
  sessions: SessionStats[],
  dailies: DailySnapshot[],
): Insights {
  const toolTotals: Record<string, number> = {};
  const commandTotals: Record<string, number> = {};
  let totalEvents = 0;
  let totalCostUSD = 0;
  let totalDurationMs = 0;

  const sessionsByDate: Record<string, number> = {};
  for (const s of sessions) {
    totalEvents += s.totalEvents;
    totalCostUSD += s.totalCostUSD;
    totalDurationMs += s.totalDurationMs;
    for (const [k, v] of Object.entries(s.toolUseCounts)) {
      toolTotals[k] = (toolTotals[k] ?? 0) + v;
    }
    for (const [k, v] of Object.entries(s.commandCounts)) {
      commandTotals[k] = (commandTotals[k] ?? 0) + v;
    }
    if (s.date) {
      sessionsByDate[s.date] = (sessionsByDate[s.date] ?? 0) + 1;
    }
  }

  const topTools = Object.entries(toolTotals)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([name, count]) => ({ name, count }));

  const topCommands = Object.entries(commandTotals)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([name, count]) => ({ name, count }));

  const busyDays = Object.entries(sessionsByDate)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([date, count]) => ({ date, sessions: count }));

  const estimatedHours = totalDurationMs > 0
    ? Math.round(totalDurationMs / 3600000 * 10) / 10
    : 0;

  // Correlations between session activity and commit output
  const correlations: string[] = [];
  const anomalies: string[] = [];

  if (sessions.length > 0 && dailies.length > 0) {
    const totalCommits = dailies.reduce((n, d) => n + d.commitCount, 0);
    const totalClosed = dailies.reduce((n, d) => n + d.closedCount, 0);

    if (totalCommits > 0 && sessions.length > 0) {
      const commitsPerSession = Math.round(totalCommits / sessions.length * 10) / 10;
      correlations.push(`${commitsPerSession} commits per session on average`);
    }

    if (totalClosed > 0 && sessions.length > 0) {
      const closedPerSession = Math.round(totalClosed / sessions.length * 10) / 10;
      correlations.push(`${closedPerSession} issues closed per session on average`);
    }

    // High-error days vs commit output
    const highErrorSessions = sessions.filter(s => s.errorCount > 10);
    if (highErrorSessions.length > 0) {
      anomalies.push(
        `${highErrorSessions.length} session${highErrorSessions.length !== 1 ? 's' : ''} had high error counts (>10) — may indicate friction in tooling or complex debugging`
      );
    }

    // Sessions with no commits on the same day
    const datesWithCommits = new Set(dailies.filter(d => d.commitCount > 0).map(d => d.date));
    const sessionDates = new Set(Object.keys(sessionsByDate));
    const sessionDaysNoCommits = [...sessionDates].filter(d => !datesWithCommits.has(d));
    if (sessionDaysNoCommits.length > 0) {
      anomalies.push(
        `Session activity on ${sessionDaysNoCommits.length} day${sessionDaysNoCommits.length !== 1 ? 's' : ''} without recorded commits — may indicate exploratory or planning work`
      );
    }

    // Most-used tool vs expected pattern
    if (topTools.length > 0 && topTools[0].count > 50) {
      correlations.push(`Heaviest tool: ${topTools[0].name} (${topTools[0].count} calls) — check for redundant reads or excessive searching`);
    }
  }

  return {
    topTools,
    topCommands,
    totalSessions: sessions.length,
    totalEvents,
    totalCostUSD,
    estimatedHours,
    avgEventsPerSession: sessions.length > 0 ? Math.round(totalEvents / sessions.length) : 0,
    busyDays,
    correlations,
    anomalies,
  };
}

// ---------------------------------------------------------------------------
// Report generation
// ---------------------------------------------------------------------------

function buildInsightReport(
  weekLabel: string,
  start: Date,
  end: Date,
  insights: Insights,
  sessionCount: number,
  dailyCount: number,
): string {
  const tz = env('DAILY_REPORTS_TIMEZONE', 'America/New_York');
  const fmt = (d: Date) => d.toLocaleDateString('en-CA', { timeZone: tz });

  const lines: string[] = [
    `# Report Insights — ${weekLabel}`,
    '',
    `> Period: ${fmt(start)} → ${fmt(end)}`,
    `> Source: ${sessionCount} Claude Code session${sessionCount !== 1 ? 's' : ''}, ${dailyCount} daily report${dailyCount !== 1 ? 's' : ''}`,
    '',
  ];

  // --- Session Overview ---
  lines.push('## Session Activity', '');
  lines.push(`- **Sessions:** ${insights.totalSessions}`);
  lines.push(`- **Total events:** ${insights.totalEvents}`);
  lines.push(`- **Avg events/session:** ${insights.avgEventsPerSession}`);
  if (insights.totalCostUSD > 0) {
    lines.push(`- **Estimated cost:** $${insights.totalCostUSD.toFixed(4)}`);
  }
  if (insights.estimatedHours > 0) {
    lines.push(`- **Estimated active time:** ${insights.estimatedHours}h`);
  }
  lines.push('');

  // --- Busiest Days ---
  if (insights.busyDays.length > 0) {
    lines.push('## Busiest Days', '');
    for (const day of insights.busyDays) {
      lines.push(`- ${day.date}: ${day.sessions} session${day.sessions !== 1 ? 's' : ''}`);
    }
    lines.push('');
  }

  // --- Top Tools ---
  if (insights.topTools.length > 0) {
    lines.push('## Top Tools Used', '');
    lines.push('| Tool | Calls |');
    lines.push('|------|-------|');
    for (const t of insights.topTools) {
      lines.push(`| \`${t.name}\` | ${t.count} |`);
    }
    lines.push('');
  }

  // --- Top Commands ---
  if (insights.topCommands.length > 0) {
    lines.push('## Top Commands Invoked', '');
    lines.push('| Command | Times |');
    lines.push('|---------|-------|');
    for (const c of insights.topCommands) {
      lines.push(`| \`${c.name}\` | ${c.count} |`);
    }
    lines.push('');
  }

  // --- Correlations ---
  if (insights.correlations.length > 0) {
    lines.push('## Correlations', '');
    for (const c of insights.correlations) {
      lines.push(`- ${c}`);
    }
    lines.push('');
  }

  // --- Anomalies ---
  if (insights.anomalies.length > 0) {
    lines.push('## Anomalies & Attention Areas', '');
    for (const a of insights.anomalies) {
      lines.push(`- ${a}`);
    }
    lines.push('');
  }

  if (insights.correlations.length === 0 && insights.anomalies.length === 0) {
    lines.push('## Correlations & Anomalies', '');
    lines.push('_Insufficient data to derive correlations this week._', '');
  }

  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const weekArg = process.argv.find(a => a.startsWith('--week='))?.replace('--week=', '');
  const { label, start, end } = resolveWeek(weekArg);

  const outPath = join(INSIGHTS_PATH, `${label}.md`);

  if (existsSync(outPath) && !FORCE) {
    console.log(`Insights already exist: ${outPath}`);
    console.log('Use --force to overwrite.');
    process.exit(0);
  }

  mkdirSync(INSIGHTS_PATH, { recursive: true });

  console.log(`Generating report insights for ${label}...`);
  console.log(`Period: ${start.toISOString().split('T')[0]} → ${end.toISOString().split('T')[0]}`);

  const sessions = collectSessionStats(start, end);
  const dailies = readDailySnapshots(start, end);

  console.log(`  sessions: ${sessions.length}`);
  console.log(`  daily reports: ${dailies.length}`);

  const insights = deriveInsights(sessions, dailies);
  const report = buildInsightReport(label, start, end, insights, sessions.length, dailies.length);

  writeFileSync(outPath, report, 'utf-8');
  console.log(`\nInsights written to: ${outPath}`);
}

main().catch(e => {
  console.error('Error generating insights:', e instanceof Error ? e.message : String(e));
  process.exit(1);
});

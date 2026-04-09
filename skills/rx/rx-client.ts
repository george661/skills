import { readFileSync, writeFileSync, appendFileSync, existsSync, mkdirSync, unlinkSync, openSync, writeSync, closeSync, constants } from 'fs';
import { homedir } from 'os';
import { join, dirname } from 'path';
import { execSync } from 'child_process';
import { fileURLToPath } from 'node:url';
import { CheckResult, LogEntry, RunSummary } from './types.js';

const RX_DIR = join(homedir(), '.claude', 'rx');
const LOG_FILE = join(RX_DIR, 'rx-log.jsonl');
const LAST_RUN_FILE = join(RX_DIR, 'last-run.json');

// --- Logging ---

export function ensureRxDir(): void {
  if (!existsSync(RX_DIR)) {
    mkdirSync(RX_DIR, { recursive: true });
  }
}

export function loadPreviousLog(): LogEntry[] {
  if (!existsSync(LOG_FILE)) return [];
  try {
    const content = readFileSync(LOG_FILE, 'utf-8').trim();
    if (!content) return [];
    return content.split('\n').map(line => JSON.parse(line));
  } catch {
    return [];
  }
}

export function appendLogEntries(runId: string, results: CheckResult[]): void {
  ensureRxDir();
  const timestamp = new Date().toISOString();
  const lines = results.map(r => JSON.stringify({
    timestamp,
    runId,
    check: r.check,
    category: r.category,
    status: r.status,
    message: r.message,
    ...(r.action && { action: r.action }),
    ...(r.error && { error: r.error }),
  }));
  appendFileSync(LOG_FILE, lines.join('\n') + '\n');
}

export function rotateLog(maxEntries = 1000): void {
  if (!existsSync(LOG_FILE)) return;
  try {
    const content = readFileSync(LOG_FILE, 'utf-8').trim();
    if (!content) return;
    const lines = content.split('\n');
    if (lines.length > maxEntries) {
      const trimmed = lines.slice(-maxEntries);
      writeFileSync(LOG_FILE, trimmed.join('\n') + '\n');
    }
  } catch {
    // Ignore rotation errors
  }
}

export function writeLastRun(summary: RunSummary): void {
  ensureRxDir();
  writeFileSync(LAST_RUN_FILE, JSON.stringify(summary, null, 2));
}

// --- Shell Execution ---

/**
 * Executes a shell command synchronously and returns the result.
 * SECURITY: `cmd` must be a trusted, hardcoded string — never derived from user input.
 * All callers in the rx codebase pass static command strings.
 */
export function exec(cmd: string, opts?: { timeout?: number }): { ok: boolean; stdout: string; stderr: string } {
  try {
    const stdout = execSync(cmd, {
      encoding: 'utf-8',
      timeout: opts?.timeout ?? 30000,
      stdio: ['pipe', 'pipe', 'pipe'],
    }).trim();
    return { ok: true, stdout, stderr: '' };
  } catch (e: unknown) {
    const err = e as { stdout?: string; stderr?: string; message?: string };
    return {
      ok: false,
      stdout: (err.stdout ?? '').toString().trim(),
      stderr: (err.stderr ?? err.message ?? '').toString().trim(),
    };
  }
}

// --- Config Loading ---

export function resolveProjectRoot(): string {
  if (process.env.PROJECT_ROOT) return process.env.PROJECT_ROOT;
  if (process.env.WORKSPACE_ROOT) return process.env.WORKSPACE_ROOT;
  // Walk up from cwd looking for .git (project workspace marker)
  let d = process.cwd();
  while (d !== dirname(d)) {
    if (existsSync(join(d, '.git'))) return d;
    d = dirname(d);
  }
  // Probe common workspace layouts under $HOME
  for (const rel of ['dev/workspace', 'projects/workspace', 'workspace']) {
    const candidate = join(homedir(), rel);
    if (existsSync(join(candidate, '.git'))) return candidate;
  }
  return join(homedir(), 'dev', 'workspace');
}

export function resolveAgentsRoot(): string {
  // Resolve relative to this file's location in the source tree
  // rx-client.ts lives at agents/.claude/skills/rx/rx-client.ts
  // So agents root is 4 levels up from __dirname
  const scriptDir = fileURLToPath(new URL('.', import.meta.url));
  const fromSource = join(scriptDir, '..', '..', '..', '..');
  if (existsSync(join(fromSource, 'config'))) return fromSource;

  // Fallback: PROJECT_ROOT/agents
  const projectRoot = resolveProjectRoot();
  return join(projectRoot, 'agents');
}

export function loadJsonConfig<T>(path: string): T | null {
  if (!existsSync(path)) return null;
  try {
    return JSON.parse(readFileSync(path, 'utf-8'));
  } catch {
    return null;
  }
}

export function loadProjectSettings(): Record<string, unknown> {
  const projectRoot = resolveProjectRoot();
  const path = join(projectRoot, '.claude', 'settings.json');
  return loadJsonConfig<Record<string, unknown>>(path) ?? {};
}

// --- Output Formatting ---

const COLORS = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  red: '\x1b[31m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  dim: '\x1b[2m',
  bold: '\x1b[1m',
};

export function formatResult(r: CheckResult): string {
  const icon = {
    pass: `${COLORS.green}[pass]${COLORS.reset}`,
    fail: `${COLORS.red}[FAIL]${COLORS.reset}`,
    fixed: `${COLORS.yellow}[fixed]${COLORS.reset}`,
    skipped: `${COLORS.dim}[skip]${COLORS.reset}`,
  }[r.status];

  let line = `  ${icon} ${r.message}`;
  if (r.action) line += ` ${COLORS.dim}-> ${r.action}${COLORS.reset}`;
  if (r.error) line += ` ${COLORS.red}(${r.error})${COLORS.reset}`;
  return line;
}

export function formatCategory(name: string): string {
  return `\n${COLORS.bold}${name}${COLORS.reset}`;
}

export function formatSummary(summary: RunSummary['summary']): string {
  const parts = [
    `${summary.total} checks`,
    `${COLORS.green}${summary.pass} pass${COLORS.reset}`,
  ];
  if (summary.fixed > 0) parts.push(`${COLORS.yellow}${summary.fixed} fixed${COLORS.reset}`);
  if (summary.fail > 0) parts.push(`${COLORS.red}${summary.fail} fail${COLORS.reset}`);
  if (summary.skipped > 0) parts.push(`${COLORS.dim}${summary.skipped} skipped${COLORS.reset}`);
  return `\nSummary: ${parts.join(' | ')}`;
}

export function generateRunId(): string {
  return `rx-${Math.floor(Date.now() / 1000)}`;
}

const LOCK_FILE = join(RX_DIR, 'rx.lock');

export function acquireLock(): boolean {
  ensureRxDir();
  try {
    // Atomic create — fails if file already exists
    const fd = openSync(LOCK_FILE, constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY);
    writeSync(fd, String(process.pid));
    closeSync(fd);
    return true;
  } catch (e: unknown) {
    const err = e as { code?: string };
    if (err.code !== 'EEXIST') return false;

    // Lock file exists — check if holder is alive
    try {
      const pid = parseInt(readFileSync(LOCK_FILE, 'utf-8').trim(), 10);
      if (isNaN(pid)) {
        unlinkSync(LOCK_FILE);
        return acquireLock(); // Retry once (corrupt lock)
      }
      try {
        process.kill(pid, 0);
        return false; // Process still running
      } catch {
        // Process gone — stale lock
        unlinkSync(LOCK_FILE);
        return acquireLock(); // Retry once
      }
    } catch {
      return false; // Can't read lock file
    }
  }
}

export function releaseLock(): void {
  try { if (existsSync(LOCK_FILE)) unlinkSync(LOCK_FILE); } catch { /* ignore */ }
}

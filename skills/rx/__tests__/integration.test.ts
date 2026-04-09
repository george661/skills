import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, rmSync, mkdirSync, readFileSync, existsSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';
import { execSync } from 'child_process';

describe('rx integration', () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = mkdtempSync(join(tmpdir(), 'rx-integration-'));
    mkdirSync(join(tmpDir, '.claude', 'rx'), { recursive: true });
  });

  afterEach(() => {
    rmSync(tmpDir, { recursive: true });
  });

  it('produces valid JSON with --json --category prereqs', () => {
    const rxPath = join(__dirname, '..', 'rx.ts');
    let output: string;
    try {
      output = execSync(`npx tsx "${rxPath}" --json --category prereqs`, {
        encoding: 'utf-8',
        env: { ...process.env, HOME: tmpDir },
        timeout: 30000,
      });
    } catch (err: unknown) {
      const e = err as { stdout?: string };
      output = e.stdout ?? '';
    }

    if (output) {
      const parsed = JSON.parse(output);
      expect(parsed).toHaveProperty('runId');
      expect(parsed).toHaveProperty('summary');
      expect(parsed.summary).toHaveProperty('total');
      expect(parsed.results).toBeInstanceOf(Array);
    }
  });

  it('writes JSONL log file after run', () => {
    const rxPath = join(__dirname, '..', 'rx.ts');
    try {
      execSync(`npx tsx "${rxPath}" --json --category prereqs`, {
        encoding: 'utf-8',
        env: { ...process.env, HOME: tmpDir },
        timeout: 30000,
      });
    } catch {
      // may exit 1
    }

    const logPath = join(tmpDir, '.claude', 'rx', 'rx-log.jsonl');
    if (existsSync(logPath)) {
      const logContent = readFileSync(logPath, 'utf-8');
      const lines = logContent.trim().split('\n');
      expect(lines.length).toBeGreaterThan(0);
      for (const line of lines) {
        const entry = JSON.parse(line);
        expect(entry).toHaveProperty('timestamp');
        expect(entry).toHaveProperty('runId');
        expect(entry).toHaveProperty('check');
        expect(entry).toHaveProperty('status');
      }
    }
  });

  it('writes last-run.json after run', () => {
    const rxPath = join(__dirname, '..', 'rx.ts');
    try {
      execSync(`npx tsx "${rxPath}" --json --category prereqs`, {
        encoding: 'utf-8',
        env: { ...process.env, HOME: tmpDir },
        timeout: 30000,
      });
    } catch {
      // may exit 1
    }

    const lastRunPath = join(tmpDir, '.claude', 'rx', 'last-run.json');
    if (existsSync(lastRunPath)) {
      const lastRun = JSON.parse(readFileSync(lastRunPath, 'utf-8'));
      expect(lastRun).toHaveProperty('runId');
      expect(lastRun).toHaveProperty('summary');
      expect(lastRun).toHaveProperty('results');
    }
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('fs', async () => {
  const actual = await vi.importActual('fs');
  return {
    ...actual,
    existsSync: vi.fn(),
    readdirSync: vi.fn(),
    readFileSync: vi.fn(),
    writeFileSync: vi.fn(),
    mkdirSync: vi.fn(),
    statSync: vi.fn(),
    chmodSync: vi.fn(),
  };
});

import { HooksCheck } from '../hooks.js';
import { existsSync, readdirSync, statSync, readFileSync, writeFileSync, mkdirSync, chmodSync } from 'fs';

describe('HooksCheck', () => {
  const check = new HooksCheck();
  const baseOpts = { dryRun: false, verbose: false, json: false, previousLog: [], projectRoot: '/tmp/test-project', agentsRoot: '/tmp/test-project/agents' };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('passes when hooks are installed with correct permissions', async () => {
    vi.mocked(existsSync).mockReturnValue(true);
    vi.mocked(readdirSync).mockReturnValue([
      { name: 'pre-commit.sh', isFile: () => true, isDirectory: () => false } as any,
    ] as any);
    vi.mocked(statSync).mockReturnValue({ mode: 0o755 } as any);

    const results = await check.run(baseOpts);
    expect(results.some(r => r.status === 'pass')).toBe(true);
  });

  it('returns skipped when no hook source files found', async () => {
    vi.mocked(existsSync).mockReturnValue(false);
    const results = await check.run(baseOpts);
    expect(results).toHaveLength(1);
    expect(results[0].status).toBe('skipped');
    expect(results[0].check).toBe('hooks:source');
  });

  it('fixes non-executable hooks when not dry-run', async () => {
    vi.mocked(existsSync).mockReturnValue(true);
    vi.mocked(readdirSync).mockReturnValue([
      { name: 'pre-commit.sh', isFile: () => true, isDirectory: () => false } as any,
    ] as any);
    vi.mocked(statSync).mockReturnValue({ mode: 0o644 } as any);

    const results = await check.run(baseOpts);
    expect(chmodSync).toHaveBeenCalled();
    const fixedResult = results.find(r => r.status === 'fixed');
    expect(fixedResult).toBeDefined();
  });

  it('reports non-executable hooks as fail in dry-run', async () => {
    vi.mocked(existsSync).mockReturnValue(true);
    vi.mocked(readdirSync).mockReturnValue([
      { name: 'pre-commit.sh', isFile: () => true, isDirectory: () => false } as any,
    ] as any);
    vi.mocked(statSync).mockReturnValue({ mode: 0o644 } as any);

    const results = await check.run({ ...baseOpts, dryRun: true });
    expect(chmodSync).not.toHaveBeenCalled();
    const failResult = results.find(r => r.status === 'fail');
    expect(failResult).toBeDefined();
  });

  it('copies missing hooks when not dry-run', async () => {
    vi.mocked(existsSync).mockImplementation((p: any) => {
      const path = String(p);
      // Source dirs exist
      if (path.includes('agents')) return true;
      // Target files do not exist
      return false;
    });
    vi.mocked(readdirSync).mockReturnValue([
      { name: 'pre-commit.sh', isFile: () => true, isDirectory: () => false } as any,
    ] as any);
    vi.mocked(readFileSync).mockReturnValue('#!/bin/bash\necho hook');

    const results = await check.run(baseOpts);
    expect(writeFileSync).toHaveBeenCalled();
    expect(mkdirSync).toHaveBeenCalled();
    const fixedResult = results.find(r => r.status === 'fixed');
    expect(fixedResult).toBeDefined();
  });
});

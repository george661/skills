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
    cpSync: vi.fn(),
  };
});

import { CommandsCheck } from '../commands.js';
import { existsSync, readdirSync, readFileSync, writeFileSync, mkdirSync } from 'fs';

describe('CommandsCheck', () => {
  const check = new CommandsCheck();
  const baseOpts = { dryRun: false, verbose: false, json: false, previousLog: [], projectRoot: '/tmp/test-project', agentsRoot: '/tmp/test-project/agents' };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('passes when command files exist in target', async () => {
    vi.mocked(existsSync).mockReturnValue(true);
    vi.mocked(readdirSync).mockReturnValue([
      { name: 'work.md', isFile: () => true, isDirectory: () => false } as any,
    ] as any);
    const results = await check.run(baseOpts);
    expect(results.some(r => r.status === 'pass')).toBe(true);
  });

  it('returns skipped when no source files found', async () => {
    vi.mocked(existsSync).mockReturnValue(false);
    const results = await check.run(baseOpts);
    expect(results).toHaveLength(1);
    expect(results[0].status).toBe('skipped');
    expect(results[0].check).toBe('commands:source');
  });

  it('copies missing command files when not dry-run', async () => {
    vi.mocked(existsSync).mockImplementation((p: any) => {
      const path = String(p);
      // Source dirs exist
      if (path.includes('agents')) return true;
      // Target files do not exist
      return false;
    });
    vi.mocked(readdirSync).mockReturnValue([
      { name: 'work.md', isFile: () => true, isDirectory: () => false } as any,
    ] as any);
    vi.mocked(readFileSync).mockReturnValue('# Work command');

    const results = await check.run(baseOpts);
    expect(results.some(r => r.status === 'fixed')).toBe(true);
    expect(writeFileSync).toHaveBeenCalled();
  });

  it('reports fail for missing commands in dry-run mode', async () => {
    vi.mocked(existsSync).mockImplementation((p: any) => {
      const path = String(p);
      if (path.includes('agents')) return true;
      return false;
    });
    vi.mocked(readdirSync).mockReturnValue([
      { name: 'work.md', isFile: () => true, isDirectory: () => false } as any,
    ] as any);

    const results = await check.run({ ...baseOpts, dryRun: true });
    expect(results.some(r => r.status === 'fail')).toBe(true);
    expect(writeFileSync).not.toHaveBeenCalled();
  });

  it('ignores non-md files in source directories', async () => {
    vi.mocked(existsSync).mockReturnValue(true);
    vi.mocked(readdirSync).mockReturnValue([
      { name: 'work.md', isFile: () => true, isDirectory: () => false } as any,
      { name: 'README.txt', isFile: () => true, isDirectory: () => false } as any,
      { name: 'script.sh', isFile: () => true, isDirectory: () => false } as any,
    ] as any);

    const results = await check.run(baseOpts);
    // Only .md files should be tracked, so only 1 installed
    const passResult = results.find(r => r.check === 'commands:files');
    expect(passResult?.status).toBe('pass');
    expect(passResult?.message).toContain('1 command files installed');
  });
});

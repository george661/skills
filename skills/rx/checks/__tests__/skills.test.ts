import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('fs', async () => {
  const actual = await vi.importActual('fs');
  return {
    ...actual,
    existsSync: vi.fn(),
    readdirSync: vi.fn(),
    mkdirSync: vi.fn(),
    cpSync: vi.fn(),
    symlinkSync: vi.fn(),
  };
});

import { SkillsCheck } from '../skills.js';
import { existsSync, readdirSync, mkdirSync, cpSync, symlinkSync } from 'fs';

describe('SkillsCheck', () => {
  const check = new SkillsCheck();
  const baseOpts = { dryRun: false, verbose: false, json: false, previousLog: [], projectRoot: '/tmp/test-project', agentsRoot: '/tmp/test-project/agents' };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('passes when skill directories exist', async () => {
    vi.mocked(existsSync).mockReturnValue(true);
    vi.mocked(readdirSync).mockReturnValue([
      { name: 'jira', isDirectory: () => true } as any,
      { name: 'bitbucket', isDirectory: () => true } as any,
    ] as any);

    const results = await check.run(baseOpts);
    const passResults = results.filter(r => r.status === 'pass');
    expect(passResults.length).toBeGreaterThan(0);
  });

  it('skips rx and __tests__ directories', async () => {
    vi.mocked(existsSync).mockReturnValue(true);
    vi.mocked(readdirSync).mockReturnValue([
      { name: 'rx', isDirectory: () => true } as any,
      { name: '__tests__', isDirectory: () => true } as any,
      { name: 'jira', isDirectory: () => true } as any,
    ] as any);

    const results = await check.run(baseOpts);
    const rxResult = results.find(r => r.check === 'skills:rx');
    const testsResult = results.find(r => r.check === 'skills:__tests__');
    expect(rxResult).toBeUndefined();
    expect(testsResult).toBeUndefined();
  });

  it('copies missing skills when not dry-run', async () => {
    const existsCalls: string[] = [];
    vi.mocked(existsSync).mockImplementation((p: any) => {
      existsCalls.push(String(p));
      // Source dirs exist, target dirs do not, project skills dir does not
      if (String(p).includes('agents')) return true;
      return false;
    });
    vi.mocked(readdirSync).mockReturnValue([
      { name: 'jira', isDirectory: () => true } as any,
    ] as any);

    const results = await check.run(baseOpts);
    const fixedResults = results.filter(r => r.status === 'fixed');
    expect(fixedResults.length).toBeGreaterThan(0);
  });

  it('reports fail for missing skills in dry-run mode', async () => {
    vi.mocked(existsSync).mockImplementation((p: any) => {
      if (String(p).includes('agents')) return true;
      return false;
    });
    vi.mocked(readdirSync).mockReturnValue([
      { name: 'jira', isDirectory: () => true } as any,
    ] as any);

    const results = await check.run({ ...baseOpts, dryRun: true });
    const failResults = results.filter(r => r.status === 'fail');
    expect(failResults.length).toBeGreaterThan(0);
    expect(cpSync).not.toHaveBeenCalled();
  });
});

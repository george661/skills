import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('fs', async () => {
  const actual = await vi.importActual('fs');
  return { ...actual, existsSync: vi.fn(), readdirSync: vi.fn() };
});
vi.mock('../../rx-client.js', () => ({
  exec: vi.fn(),
}));

import { WorktreesCheck } from '../worktrees.js';
import { existsSync, readdirSync } from 'fs';
import { exec } from '../../rx-client.js';

describe('WorktreesCheck', () => {
  const check = new WorktreesCheck();
  const baseOpts = { dryRun: false, verbose: false, json: false, previousLog: [], projectRoot: '/tmp/test-project', agentsRoot: '/tmp/test-project/agents' };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('passes when no worktrees directory exists', async () => {
    vi.mocked(existsSync).mockReturnValue(false);
    const results = await check.run(baseOpts);
    expect(results[0]?.status).toBe('pass');
    expect(results[0]?.message).toContain('clean');
  });

  it('reports stale worktree as fail', async () => {
    vi.mocked(existsSync).mockReturnValue(true);
    vi.mocked(readdirSync)
      .mockReturnValueOnce([{ name: 'api-service', isDirectory: () => true }] as any) // repoDirs
      .mockReturnValueOnce([{ name: 'PROJ-123-fix-bug', isDirectory: () => true }] as any); // trees
    vi.mocked(exec)
      .mockReturnValueOnce({ ok: true, stdout: 'PROJ-123-fix-bug', stderr: '' }) // branch
      .mockReturnValueOnce({ ok: true, stdout: 'refs/remotes/origin/main', stderr: '' }) // defaultBranch
      .mockReturnValueOnce({ ok: true, stdout: '', stderr: '' }); // merged check

    const results = await check.run(baseOpts);
    expect(results.some(r => r.status === 'fail' && r.message.includes('stale'))).toBe(true);
  });
});

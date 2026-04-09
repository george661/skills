import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('fs', async () => {
  const actual = await vi.importActual('fs');
  return { ...actual, existsSync: vi.fn() };
});
vi.mock('../../rx-client.js', () => ({
  exec: vi.fn(),
  loadJsonConfig: vi.fn(),
}));

import { ReposCheck } from '../repos.js';
import { exec, loadJsonConfig } from '../../rx-client.js';
import { existsSync } from 'fs';
import type { Repository } from '../../types.js';

describe('ReposCheck', () => {
  const check = new ReposCheck();
  const baseOpts = { dryRun: false, verbose: false, json: false, previousLog: [], projectRoot: '/tmp/test-project', agentsRoot: '/tmp/test-project/agents' };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('passes when repo directory exists and is a git repo', async () => {
    vi.mocked(loadJsonConfig).mockReturnValue([
      { name: 'api-service', git_url: 'git@bitbucket.org:your-org/api-service.git', description: 'API', required: true },
    ] as Repository[]);
    vi.mocked(existsSync).mockReturnValue(true);
    vi.mocked(exec).mockReturnValue({ ok: true, stdout: 'true', stderr: '' });

    const results = await check.run(baseOpts);
    expect(results[0]?.status).toBe('pass');
  });

  it('clones missing required repo', async () => {
    vi.mocked(loadJsonConfig).mockReturnValue([
      { name: 'api-service', git_url: 'git@bitbucket.org:your-org/api-service.git', description: 'API', required: true },
    ] as Repository[]);
    vi.mocked(existsSync).mockReturnValue(false);
    vi.mocked(exec).mockReturnValue({ ok: true, stdout: '', stderr: '' });

    const results = await check.run(baseOpts);
    expect(results[0]?.status).toBe('fixed');
    expect(results[0]?.action).toContain('git clone');
  });

  it('skips when no repos configured', async () => {
    vi.mocked(loadJsonConfig).mockReturnValue(null);
    const results = await check.run(baseOpts);
    expect(results[0]?.status).toBe('skipped');
  });
});

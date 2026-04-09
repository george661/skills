import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../rx-client.js', () => ({
  exec: vi.fn(),
  loadJsonConfig: vi.fn(),
}));

import { BrewCheck } from '../brew.js';
import { exec, loadJsonConfig } from '../../rx-client.js';

describe('BrewCheck', () => {
  const check = new BrewCheck();
  const baseOpts = { dryRun: false, verbose: false, json: false, previousLog: [], projectRoot: '/tmp', agentsRoot: '/tmp/agents' };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('passes when all packages are installed', async () => {
    vi.mocked(loadJsonConfig).mockReturnValue([
      { name: 'jq', required: true, description: 'JSON processor', version_command: 'jq --version' },
    ]);
    vi.mocked(exec).mockReturnValue({ ok: true, stdout: 'jq-1.7.1', stderr: '' });

    const results = await check.run(baseOpts);
    expect(results[0]?.status).toBe('pass');
  });

  it('fixes missing required package', async () => {
    vi.mocked(loadJsonConfig).mockReturnValue([
      { name: 'tokei', required: true, description: 'Code stats', version_command: 'tokei --version' },
    ]);
    vi.mocked(exec)
      .mockReturnValueOnce({ ok: false, stdout: '', stderr: 'not found' })  // brew list
      .mockReturnValueOnce({ ok: true, stdout: '', stderr: '' });            // brew install

    const results = await check.run(baseOpts);
    expect(results[0]?.status).toBe('fixed');
    expect(results[0]?.action).toContain('brew install');
  });

  it('skips when no packages configured', async () => {
    vi.mocked(loadJsonConfig).mockReturnValue(null);
    const results = await check.run(baseOpts);
    expect(results[0]?.status).toBe('skipped');
  });
});

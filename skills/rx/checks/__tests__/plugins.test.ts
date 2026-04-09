import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../rx-client.js', () => ({
  exec: vi.fn(),
  loadJsonConfig: vi.fn(),
}));

import { PluginsCheck } from '../plugins.js';
import { exec, loadJsonConfig } from '../../rx-client.js';

describe('PluginsCheck', () => {
  const check = new PluginsCheck();
  const baseOpts = { dryRun: false, verbose: false, json: false, previousLog: [], projectRoot: '/tmp/test-project', agentsRoot: '/tmp/test-project/agents' };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('skips when no plugins configured', async () => {
    vi.mocked(loadJsonConfig).mockReturnValue(null);
    const results = await check.run(baseOpts);
    expect(results[0]?.status).toBe('skipped');
  });

  it('passes when plugin is installed (CLI detection)', async () => {
    vi.mocked(loadJsonConfig).mockReturnValue([
      { name: 'superpowers', marketplace: 'claude-plugins-official', required: true },
    ]);
    vi.mocked(exec).mockReturnValue({ ok: true, stdout: 'superpowers@claude-plugins-official', stderr: '' });
    const results = await check.run(baseOpts);
    expect(results[0]?.status).toBe('pass');
  });
});

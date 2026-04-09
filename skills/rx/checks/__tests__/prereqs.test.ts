import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock exec before importing
vi.mock('../../rx-client.js', () => ({
  exec: vi.fn(),
}));

import { PrereqsCheck } from '../prereqs.js';
import { exec } from '../../rx-client.js';

describe('PrereqsCheck', () => {
  const check = new PrereqsCheck();
  const baseOpts = { dryRun: false, verbose: false, json: false, previousLog: [], projectRoot: '/tmp', agentsRoot: '/tmp' };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('passes when node v20+ is found', async () => {
    vi.mocked(exec).mockReturnValue({ ok: true, stdout: 'v20.11.0', stderr: '' });
    const results = await check.run(baseOpts);
    const nodeResult = results.find(r => r.check === 'prereqs:node');
    expect(nodeResult?.status).toBe('pass');
  });

  it('fails when node is missing', async () => {
    vi.mocked(exec).mockReturnValue({ ok: false, stdout: '', stderr: 'not found' });
    const results = await check.run(baseOpts);
    const nodeResult = results.find(r => r.check === 'prereqs:node');
    expect(nodeResult?.status).toBe('fail');
  });
});

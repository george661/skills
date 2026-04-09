import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('fs', async () => {
  const actual = await vi.importActual('fs');
  return { ...actual, existsSync: vi.fn() };
});
vi.mock('../../rx-client.js', () => ({
  exec: vi.fn(),
  loadJsonConfig: vi.fn(),
}));

import { SupergatewayCheck } from '../supergateway.js';
import { exec, loadJsonConfig } from '../../rx-client.js';
import { existsSync } from 'fs';

describe('SupergatewayCheck', () => {
  const check = new SupergatewayCheck();
  const baseOpts = { dryRun: false, verbose: false, json: false, previousLog: [], projectRoot: '/tmp/test-project', agentsRoot: '/tmp/test-project/agents' };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('skips when no servers configured', async () => {
    vi.mocked(loadJsonConfig).mockReturnValue({ servers: {} });
    const results = await check.run(baseOpts);
    expect(results[0]?.status).toBe('skipped');
  });

  it('fails when config missing', async () => {
    vi.mocked(loadJsonConfig).mockReturnValue(null);
    const results = await check.run(baseOpts);
    expect(results[0]?.status).toBe('fail');
  });

  it('passes when server is listening', async () => {
    vi.mocked(loadJsonConfig).mockReturnValue({
      servers: { 'test-server': { command: 'node test', port: 3100, scope: 'user', description: 'Test' } },
    });
    vi.mocked(exec).mockReturnValue({ ok: true, stdout: '12345', stderr: '' });
    vi.mocked(existsSync).mockReturnValue(false);

    const results = await check.run(baseOpts);
    expect(results[0]?.status).toBe('pass');
  });
});

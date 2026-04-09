import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../rx-client.js', () => ({
  exec: vi.fn(),
  loadJsonConfig: vi.fn(),
}));

import { CredentialsCheck } from '../credentials.js';
import { loadJsonConfig, exec } from '../../rx-client.js';

describe('CredentialsCheck', () => {
  const check = new CredentialsCheck();
  const baseOpts = { dryRun: false, verbose: false, json: false, previousLog: [], projectRoot: '/tmp/test-project', agentsRoot: '/tmp/test-project/agents' };

  beforeEach(() => {
    vi.clearAllMocks();
    // Mock global fetch
    global.fetch = vi.fn();
  });

  it('fails when no credentials file exists', async () => {
    vi.mocked(loadJsonConfig).mockReturnValue(null);
    vi.mocked(exec).mockReturnValue({ ok: false, stdout: '', stderr: '' });
    const results = await check.run(baseOpts);
    const jiraResult = results.find(r => r.check === 'credentials:jira');
    expect(jiraResult?.status).toBe('fail');
  });

  it('passes jira when credentials valid and API responds ok', async () => {
    vi.mocked(loadJsonConfig).mockReturnValue({
      jira: { host: 'test.atlassian.net', username: 'user@test.com', apiToken: 'tok123' },
    });
    vi.mocked(global.fetch).mockResolvedValue({ ok: true } as Response);
    vi.mocked(exec).mockReturnValue({ ok: false, stdout: '', stderr: '' });

    const results = await check.run(baseOpts);
    const jiraResult = results.find(r => r.check === 'credentials:jira');
    expect(jiraResult?.status).toBe('pass');
  });
});

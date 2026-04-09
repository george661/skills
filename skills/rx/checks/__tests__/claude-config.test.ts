import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('fs', async () => {
  const actual = await vi.importActual('fs');
  return { ...actual, existsSync: vi.fn(), mkdirSync: vi.fn() };
});
vi.mock('../../rx-client.js', () => ({
  loadJsonConfig: vi.fn(),
}));

import { ClaudeConfigCheck } from '../claude-config.js';
import { existsSync, mkdirSync } from 'fs';
import { loadJsonConfig } from '../../rx-client.js';

describe('ClaudeConfigCheck', () => {
  const check = new ClaudeConfigCheck();
  const baseOpts = { dryRun: false, verbose: false, json: false, previousLog: [], projectRoot: '/tmp/test-project', agentsRoot: '/tmp/test-project/agents' };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('passes when all directories exist', async () => {
    vi.mocked(existsSync).mockReturnValue(true);
    vi.mocked(loadJsonConfig).mockReturnValue({ permissions: {} });
    const results = await check.run(baseOpts);
    const dirResults = results.filter(r => r.check.includes(':dir'));
    expect(dirResults.every(r => r.status === 'pass')).toBe(true);
  });

  it('creates missing directories when not dry-run', async () => {
    vi.mocked(existsSync).mockReturnValue(false);
    vi.mocked(loadJsonConfig).mockReturnValue(null);
    const results = await check.run(baseOpts);
    const fixedResults = results.filter(r => r.status === 'fixed');
    expect(fixedResults.length).toBeGreaterThan(0);
  });

  it('reports fail for missing directories in dry-run mode', async () => {
    vi.mocked(existsSync).mockReturnValue(false);
    vi.mocked(loadJsonConfig).mockReturnValue(null);
    const results = await check.run({ ...baseOpts, dryRun: true });
    const failResults = results.filter(r => r.check.includes(':dir') && r.status === 'fail');
    expect(failResults.length).toBe(7); // 4 global + 3 project dirs
  });

  it('passes when global settings.json exists', async () => {
    vi.mocked(existsSync).mockReturnValue(true);
    vi.mocked(loadJsonConfig).mockReturnValue({ some: 'config' });
    const results = await check.run(baseOpts);
    const settingsResult = results.find(r => r.check === 'claude-config:global-settings');
    expect(settingsResult?.status).toBe('pass');
  });

  it('fails when global settings.json is missing', async () => {
    vi.mocked(existsSync).mockReturnValue(true);
    vi.mocked(loadJsonConfig).mockReturnValue(null);
    const results = await check.run(baseOpts);
    const settingsResult = results.find(r => r.check === 'claude-config:global-settings');
    expect(settingsResult?.status).toBe('fail');
  });

  it('does not call mkdirSync in dry-run mode', async () => {
    vi.mocked(existsSync).mockReturnValue(false);
    vi.mocked(loadJsonConfig).mockReturnValue(null);
    await check.run({ ...baseOpts, dryRun: true });
    expect(mkdirSync).not.toHaveBeenCalled();
  });
});

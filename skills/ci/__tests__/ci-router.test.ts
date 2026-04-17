import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { SpawnSyncReturns } from 'child_process';

// Mock child_process and fs before importing the module
vi.mock('child_process', () => ({
  spawnSync: vi.fn(),
}));

vi.mock('fs', () => ({
  existsSync: vi.fn(),
}));

describe('CI Router', () => {
  let resolveCIProvider: any;
  let translateParams: any;
  let delegateCI: any;
  let spawnSync: any;
  let existsSync: any;
  
  const origEnv = { ...process.env };

  beforeEach(async () => {
    vi.clearAllMocks();
    vi.resetModules();
    
    // Reset env
    process.env = { ...origEnv };
    delete process.env.CI_PROVIDER;
    delete process.env.GITHUB_OWNER;

    // Re-import mocked modules
    const childProcess = await import('child_process');
    const fs = await import('fs');
    spawnSync = childProcess.spawnSync;
    existsSync = fs.existsSync;

    // Default: files exist
    vi.mocked(existsSync).mockReturnValue(true);

    // Import module under test
    const ciRouter = await import('../ci-router.js');
    resolveCIProvider = ciRouter.resolveCIProvider;
    translateParams = ciRouter.translateParams;
    delegateCI = ciRouter.delegateCI;
  });

  afterEach(() => {
    process.env = { ...origEnv };
  });

  describe('resolveCIProvider()', () => {
    it('returns concourse when CI_PROVIDER is unset', () => {
      delete process.env.CI_PROVIDER;
      expect(resolveCIProvider()).toBe('concourse');
    });

    it('returns github_actions when CI_PROVIDER=github_actions', () => {
      process.env.CI_PROVIDER = 'github_actions';
      expect(resolveCIProvider()).toBe('github_actions');
    });

    it('returns circleci when CI_PROVIDER=circleci', () => {
      process.env.CI_PROVIDER = 'circleci';
      expect(resolveCIProvider()).toBe('circleci');
    });

    it('returns explicit provider over env var', () => {
      process.env.CI_PROVIDER = 'circleci';
      expect(resolveCIProvider('github_actions')).toBe('github_actions');
    });

    it('returns concourse for invalid explicit provider', () => {
      expect(resolveCIProvider('invalid')).toBe('concourse');
    });

    it('returns concourse for invalid env var', () => {
      process.env.CI_PROVIDER = 'invalid';
      expect(resolveCIProvider()).toBe('concourse');
    });
  });

  describe('translateParams()', () => {
    it('concourse: maps repo → pipeline', () => {
      const params = { repo: 'my-api', build_id: '123' };
      const result = translateParams('concourse', 'get_build_status', params);
      
      expect(result.pipeline).toBe('my-api');
      expect(result.build_id).toBe('123');
      expect(result.repo).toBeUndefined();
      expect(result.provider).toBeUndefined();
    });

    it('concourse: passes through other params', () => {
      const params = { job_name: 'test', timeout_seconds: 60 };
      const result = translateParams('concourse', 'trigger_build', params);
      
      expect(result.job_name).toBe('test');
      expect(result.timeout_seconds).toBe(60);
    });

    it('github_actions: injects owner from GITHUB_OWNER env', () => {
      process.env.GITHUB_OWNER = 'test-org';
      const params = { repo: 'test-repo', run_id: 123 };
      const result = translateParams('github_actions', 'get_build_status', params);
      
      expect(result.owner).toBe('test-org');
      expect(result.repo).toBe('test-repo');
      expect(result.run_id).toBe(123);
      expect(result.provider).toBeUndefined();
    });

    it('github_actions: preserves explicit owner param', () => {
      process.env.GITHUB_OWNER = 'env-org';
      const params = { owner: 'explicit-org', repo: 'test-repo' };
      const result = translateParams('github_actions', 'get_build_status', params);
      
      expect(result.owner).toBe('explicit-org');
    });

    it('github_actions: no owner injection if not in env', () => {
      delete process.env.GITHUB_OWNER;
      const params = { repo: 'test-repo', run_id: 123 };
      const result = translateParams('github_actions', 'get_build_status', params);
      
      expect(result.owner).toBeUndefined();
      expect(result.repo).toBe('test-repo');
    });

    it('circleci: passes through unchanged', () => {
      const params = { project_slug: 'gh/org/repo', pipeline_id: '123' };
      const result = translateParams('circleci', 'get_build_status', params);
      
      expect(result).toEqual(params);
    });

    it('cleans provider field from params', () => {
      const params = { provider: 'github_actions', repo: 'test' };
      const resultConcourse = translateParams('concourse', 'skill', params);
      const resultGH = translateParams('github_actions', 'skill', params);
      
      expect(resultConcourse.provider).toBeUndefined();
      expect(resultGH.provider).toBeUndefined();
    });
  });

  describe('delegateCI() skill mapping', () => {
    beforeEach(() => {
      vi.mocked(spawnSync).mockReturnValue({
        status: 0,
        stdout: '{"success": true}',
        stderr: '',
        error: undefined,
      } as SpawnSyncReturns<string>);
    });

    it('maps get_build_status to concourse/get_build', () => {
      delegateCI('concourse', 'get_build_status', { pipeline: 'test' });

      expect(vi.mocked(spawnSync)).toHaveBeenCalledWith(
        'npx',
        expect.arrayContaining([
          'tsx',
          expect.stringContaining('concourse/get_build.ts'),
        ]),
        expect.any(Object)
      );
    });

    it('maps get_build_status to github-actions/get_workflow_run', () => {
      delegateCI('github_actions', 'get_build_status', { repo: 'test', run_id: 123 });

      expect(vi.mocked(spawnSync)).toHaveBeenCalledWith(
        'npx',
        expect.arrayContaining([
          'tsx',
          expect.stringContaining('github-actions/get_workflow_run.ts'),
        ]),
        expect.any(Object)
      );
    });

    it('maps trigger_build to fly/trigger_job for concourse', () => {
      delegateCI('concourse', 'trigger_build', { pipeline: 'test' });

      expect(vi.mocked(spawnSync)).toHaveBeenCalledWith(
        'npx',
        expect.arrayContaining([
          'tsx',
          expect.stringContaining('fly/trigger_job.ts'),
        ]),
        expect.any(Object)
      );
    });

    it('maps trigger_build to github-actions/trigger_workflow', () => {
      delegateCI('github_actions', 'trigger_build', { repo: 'test' });

      expect(vi.mocked(spawnSync)).toHaveBeenCalledWith(
        'npx',
        expect.arrayContaining([
          'tsx',
          expect.stringContaining('github-actions/trigger_workflow.ts'),
        ]),
        expect.any(Object)
      );
    });

    it('maps list_builds to concourse/list_builds', () => {
      delegateCI('concourse', 'list_builds', { pipeline: 'test' });

      expect(vi.mocked(spawnSync)).toHaveBeenCalledWith(
        'npx',
        expect.arrayContaining([
          'tsx',
          expect.stringContaining('concourse/list_builds.ts'),
        ]),
        expect.any(Object)
      );
    });

    it('throws error when skill file does not exist', () => {
      vi.mocked(existsSync).mockReturnValue(false);
      
      expect(() => {
        delegateCI('concourse', 'nonexistent', { pipeline: 'test' });
      }).toThrow(/CI skill not found/);
    });

    it('throws error when subprocess exits with non-zero status', () => {
      vi.mocked(spawnSync).mockReturnValue({
        status: 1,
        stdout: '',
        stderr: 'Error: pipeline not found',
        error: undefined,
      } as SpawnSyncReturns<string>);
      
      expect(() => {
        delegateCI('concourse', 'get_build_status', { pipeline: 'test' });
      }).toThrow(/pipeline not found/);
    });

    it('translates params before delegating', () => {
      delegateCI('concourse', 'get_build_status', { repo: 'my-api', build_id: '123' });

      const call = vi.mocked(spawnSync).mock.calls[0];
      const jsonArg = call[1][2];
      const params = JSON.parse(jsonArg);
      
      expect(params.pipeline).toBe('my-api');
      expect(params.build_id).toBe('123');
      expect(params.repo).toBeUndefined();
    });
  });
});

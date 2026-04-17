import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { SpawnSyncReturns } from 'child_process';

// Mock child_process and fs before importing the module
vi.mock('child_process', () => ({
  spawnSync: vi.fn(),
  execSync: vi.fn(),
}));

vi.mock('fs', () => ({
  readFileSync: vi.fn(),
  existsSync: vi.fn(),
}));

describe('VCS Router', () => {
  // Import after mocks are set up
  let resolve: any;
  let delegate: any;
  let VcsContext: any;
  let spawnSync: any;
  let execSync: any;
  let readFileSync: any;
  let existsSync: any;

  beforeEach(async () => {
    vi.clearAllMocks();
    vi.resetModules(); // Clear module cache to reset _configCache
    
    // Re-import mocked modules
    const childProcess = await import('child_process');
    const fs = await import('fs');
    spawnSync = childProcess.spawnSync;
    execSync = childProcess.execSync;
    readFileSync = fs.readFileSync;
    existsSync = fs.existsSync;

    // Default: config doesn't exist
    vi.mocked(existsSync).mockReturnValue(false);
    // Default: execSync fails (no git remote)
    vi.mocked(execSync).mockImplementation(() => {
      throw new Error('git remote not found');
    });

    // Import module under test
    const vcsRouter = await import('../vcs-router.js');
    resolve = vcsRouter.resolve;
    delegate = vcsRouter.delegate;
    VcsContext = vcsRouter.VcsContext;
  });

  describe('resolve()', () => {
    it('uses explicit provider when provided', () => {
      const ctx = resolve('test-repo', 'github');
      expect(ctx.provider).toBe('github');
      expect(ctx.localRepo).toBe('test-repo');
      expect(ctx.ci).toBe('github-actions');
    });

    it('reads config file when present', async () => {
      vi.mocked(existsSync).mockImplementation((path: any) => {
        return path.toString().includes('repo-vcs.json');
      });
      vi.mocked(readFileSync).mockReturnValue(
        JSON.stringify({
          'test-repo': {
            provider: 'github',
            owner: 'test-org',
            remote_repo: 'test-remote-repo',
            ci: 'github-actions',
          },
        })
      );

      const ctx = resolve('test-repo');
      expect(ctx.provider).toBe('github');
      expect(ctx.owner).toBe('test-org');
      expect(ctx.remoteRepo).toBe('test-remote-repo');
      expect(ctx.ci).toBe('github-actions');
    });

    it('detects github from git remote URL', () => {
      vi.mocked(execSync).mockReturnValue('git@github.com:test-org/test-repo.git\n' as any);
      
      const ctx = resolve('test-repo');
      expect(ctx.provider).toBe('github');
      expect(ctx.owner).toBe('test-org');
      expect(ctx.ci).toBe('github-actions');
    });

    it('detects bitbucket from git remote URL', () => {
      vi.mocked(execSync).mockReturnValue('git@bitbucket.org:test-workspace/test-repo.git\n' as any);
      
      const ctx = resolve('test-repo');
      expect(ctx.provider).toBe('bitbucket');
      expect(ctx.owner).toBe('test-workspace');
      expect(ctx.ci).toBe('concourse');
    });

    it('defaults to bitbucket when no detection works', () => {
      const ctx = resolve('test-repo');
      expect(ctx.provider).toBe('bitbucket');
      expect(ctx.ci).toBe('concourse');
      expect(ctx.localRepo).toBe('test-repo');
    });

    it('falls back to bitbucket for unknown explicit provider', () => {
      // @ts-expect-error testing invalid provider
      const ctx = resolve('test-repo', 'unknown');
      expect(ctx.provider).toBe('bitbucket');
    });
  });

  describe('delegate() parameter translation', () => {
    beforeEach(() => {
      // Mock successful subprocess execution
      vi.mocked(existsSync).mockReturnValue(true);
      vi.mocked(spawnSync).mockReturnValue({
        status: 0,
        stdout: '{"success": true}',
        stderr: '',
        error: undefined,
      } as SpawnSyncReturns<string>);
    });

    it('translates GitHub params: pr_number → pull_number', async () => {
      const ctx = {
        provider: 'github' as const,
        owner: 'test-org',
        remoteRepo: 'test-repo',
        ci: 'github-actions' as const,
        localRepo: 'test-repo',
      };

      await delegate(ctx, 'get_pull_request', { pr_number: 42 });

      expect(vi.mocked(spawnSync)).toHaveBeenCalledWith(
        'npx',
        expect.arrayContaining([
          'tsx',
          expect.stringContaining('github-mcp/get_pull_request.ts'),
          expect.stringContaining('"pull_number":42'),
        ]),
        expect.any(Object)
      );
    });

    it('translates GitHub params: repo → remoteRepo', async () => {
      const ctx = {
        provider: 'github' as const,
        owner: 'test-org',
        remoteRepo: 'remote-name',
        ci: 'github-actions' as const,
        localRepo: 'local-name',
      };

      await delegate(ctx, 'get_pull_request', { repo: 'local-name', pr_number: 42 });

      const call = vi.mocked(spawnSync).mock.calls[0];
      const jsonArg = call[1][2];
      const params = JSON.parse(jsonArg);
      
      expect(params.repo).toBe('remote-name');
      expect(params.owner).toBe('test-org');
    });

    it('translates GitHub params: comment_text → body', async () => {
      const ctx = {
        provider: 'github' as const,
        owner: 'test-org',
        remoteRepo: 'test-repo',
        ci: 'github-actions' as const,
        localRepo: 'test-repo',
      };

      await delegate(ctx, 'add_pr_comment', { pr_number: 42, comment_text: 'Hello' });

      const call = vi.mocked(spawnSync).mock.calls[0];
      const jsonArg = call[1][2];
      const params = JSON.parse(jsonArg);
      
      expect(params.body).toBe('Hello');
      expect(params.comment_text).toBeUndefined();
    });

    it('translates GitHub params: source_branch → head, target_branch → base', async () => {
      const ctx = {
        provider: 'github' as const,
        owner: 'test-org',
        remoteRepo: 'test-repo',
        ci: 'github-actions' as const,
        localRepo: 'test-repo',
      };

      await delegate(ctx, 'create_pull_request', {
        title: 'Test PR',
        source_branch: 'feature',
        target_branch: 'main',
        description: 'Test description',
      });

      const call = vi.mocked(spawnSync).mock.calls[0];
      const jsonArg = call[1][2];
      const params = JSON.parse(jsonArg);
      
      expect(params.head).toBe('feature');
      expect(params.base).toBe('main');
      expect(params.body).toBe('Test description');
      expect(params.source_branch).toBeUndefined();
      expect(params.target_branch).toBeUndefined();
      expect(params.description).toBeUndefined();
    });

    it('translates Bitbucket params: repo → repo_slug', async () => {
      const ctx = {
        provider: 'bitbucket' as const,
        owner: 'test-workspace',
        remoteRepo: 'test-repo-slug',
        ci: 'concourse' as const,
        localRepo: 'test-repo',
      };

      await delegate(ctx, 'get_pull_request', { repo: 'test-repo', pr_number: 42 });

      const call = vi.mocked(spawnSync).mock.calls[0];
      const jsonArg = call[1][2];
      const params = JSON.parse(jsonArg);
      
      expect(params.repo_slug).toBe('test-repo-slug');
      expect(params.pull_request_id).toBe(42);
      expect(params.repo).toBeUndefined();
      expect(params.pr_number).toBeUndefined();
    });

    it('translates Bitbucket params: comment_text → content', async () => {
      const ctx = {
        provider: 'bitbucket' as const,
        owner: 'test-workspace',
        remoteRepo: 'test-repo',
        ci: 'concourse' as const,
        localRepo: 'test-repo',
      };

      await delegate(ctx, 'add_pr_comment', { pr_number: 42, comment_text: 'Hello' });

      const call = vi.mocked(spawnSync).mock.calls[0];
      const jsonArg = call[1][2];
      const params = JSON.parse(jsonArg);
      
      expect(params.content).toBe('Hello');
      expect(params.comment_text).toBeUndefined();
      expect(params.owner).toBeUndefined(); // Bitbucket doesn't use owner
    });

    it('throws error when skill file does not exist', async () => {
      vi.mocked(existsSync).mockReturnValue(false);
      
      const ctx = {
        provider: 'github' as const,
        owner: 'test-org',
        remoteRepo: 'test-repo',
        ci: 'github-actions' as const,
        localRepo: 'test-repo',
      };

      await expect(
        delegate(ctx, 'nonexistent_skill', {})
      ).rejects.toThrow(/VCS skill not found/);
    });

    it('throws error when subprocess exits with non-zero status', async () => {
      vi.mocked(spawnSync).mockReturnValue({
        status: 1,
        stdout: '',
        stderr: 'Error: something went wrong',
        error: undefined,
      } as SpawnSyncReturns<string>);
      
      const ctx = {
        provider: 'github' as const,
        owner: 'test-org',
        remoteRepo: 'test-repo',
        ci: 'github-actions' as const,
        localRepo: 'test-repo',
      };

      await expect(
        delegate(ctx, 'get_pull_request', { pr_number: 42 })
      ).rejects.toThrow(/something went wrong/);
    });
  });
});

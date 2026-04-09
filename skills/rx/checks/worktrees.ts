import { Check, CheckResult, RunOpts } from '../types.js';
import { exec } from '../rx-client.js';
import { existsSync, readdirSync } from 'fs';
import { join } from 'path';

export class WorktreesCheck implements Check {
  name = 'worktrees';
  category = 'Worktrees';

  async run(opts: RunOpts): Promise<CheckResult[]> {
    const results: CheckResult[] = [];
    const worktreesDir = join(opts.projectRoot, 'worktrees');

    if (!existsSync(worktreesDir)) {
      results.push({
        check: 'worktrees:dir', category: this.category, status: 'pass',
        message: 'No worktrees directory (clean)',
      });
      return results;
    }

    let repoDirs: { name: string }[];
    try {
      repoDirs = readdirSync(worktreesDir, { withFileTypes: true })
        .filter(d => d.isDirectory());
    } catch {
      results.push({
        check: 'worktrees:dir', category: this.category, status: 'fail',
        message: 'Cannot read worktrees directory',
      });
      return results;
    }

    if (repoDirs.length === 0) {
      results.push({
        check: 'worktrees:dir', category: this.category, status: 'pass',
        message: 'Worktrees directory empty (clean)',
      });
      return results;
    }

    for (const repoDir of repoDirs) {
      const repoWorktrees = join(worktreesDir, repoDir.name);
      let trees: { name: string }[];
      try {
        trees = readdirSync(repoWorktrees, { withFileTypes: true })
          .filter(d => d.isDirectory());
      } catch {
        continue;
      }

      for (const tree of trees) {
        const treePath = join(repoWorktrees, tree.name);
        const branch = exec(`git -C "${treePath}" branch --show-current`);

        if (!branch.ok) {
          results.push({
            check: `worktrees:${repoDir.name}/${tree.name}`, category: this.category,
            status: 'skipped',
            message: `${tree.name} — not a valid worktree`,
          });
          continue;
        }

        const mainRepo = join(opts.projectRoot, repoDir.name);
        const defaultBranch = exec(`git -C "${mainRepo}" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null`);
        const baseBranch = defaultBranch.ok
          ? defaultBranch.stdout.replace('refs/remotes/origin/', '').trim()
          : 'main';
        const merged = exec(`git -C "${mainRepo}" branch --merged ${baseBranch} | grep -qF "${branch.stdout.trim()}"`);

        results.push({
          check: `worktrees:${repoDir.name}/${tree.name}`, category: this.category,
          status: merged.ok ? 'fail' : 'pass',
          message: merged.ok
            ? `${tree.name} — branch merged, worktree is stale`
            : `${tree.name} — active (branch: ${branch.stdout.trim()})`,
          ...(merged.ok && { error: `Run: git -C ${mainRepo} worktree remove ${treePath}` }),
        });
      }
    }

    return results;
  }
}

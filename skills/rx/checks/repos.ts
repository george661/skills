import { existsSync } from 'fs';
import { join } from 'path';
import { Check, CheckResult, RunOpts, Repository } from '../types.js';
import { exec, loadJsonConfig } from '../rx-client.js';

export class ReposCheck implements Check {
  name = 'repos';
  category = 'Repositories';

  async run(opts: RunOpts): Promise<CheckResult[]> {
    const results: CheckResult[] = [];
    const repos = loadJsonConfig<Repository[]>(
      join(opts.agentsRoot, 'config', 'repositories.json')
    ) ?? [];

    if (repos.length === 0) {
      results.push({
        check: 'repos:config', category: this.category, status: 'skipped',
        message: 'No repositories configured (config/repositories.json missing)',
      });
      return results;
    }

    for (const repo of repos) {
      const repoPath = join(opts.projectRoot, repo.name);

      if (existsSync(repoPath)) {
        const isGit = exec(`git -C "${repoPath}" rev-parse --is-inside-work-tree`);
        if (isGit.ok) {
          results.push({
            check: `repos:${repo.name}`, category: this.category, status: 'pass',
            message: `${repo.name} exists at ${repoPath}`,
          });
        } else {
          results.push({
            check: `repos:${repo.name}`, category: this.category, status: 'fail',
            message: `${repo.name} exists but is not a git repo`,
            error: `${repoPath} is not a valid git repository`,
          });
        }
      } else if (!opts.dryRun) {
        const clone = exec(`git clone "${repo.git_url}" "${repoPath}"`, { timeout: 120000 });
        results.push({
          check: `repos:${repo.name}`, category: this.category,
          status: clone.ok ? 'fixed' : (repo.required ? 'fail' : 'skipped'),
          message: `${repo.name} not found`,
          ...(clone.ok ? { action: `git clone ${repo.git_url}` } : { error: clone.stderr }),
        });
      } else {
        results.push({
          check: `repos:${repo.name}`, category: this.category,
          status: repo.required ? 'fail' : 'skipped',
          message: `${repo.name} not found (dry-run: would git clone)`,
        });
      }
    }

    return results;
  }
}

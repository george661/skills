import { readdirSync, existsSync, cpSync, symlinkSync, mkdirSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';
import { Check, CheckResult, RunOpts } from '../types.js';

export class SkillsCheck implements Check {
  name = 'skills';
  category = 'Skills';

  async run(opts: RunOpts): Promise<CheckResult[]> {
    const results: CheckResult[] = [];
    const globalSkillsDir = join(homedir(), '.claude', 'skills');

    // Discover integrations from source directories
    const baseSrc = join(opts.agentsRoot, 'base', '.claude', 'skills');
    const tenantSrc = join(opts.agentsRoot, '.claude', 'skills');

    const integrations = new Set<string>();
    if (existsSync(baseSrc)) {
      try {
        readdirSync(baseSrc, { withFileTypes: true })
          .filter(d => d.isDirectory()).forEach(d => integrations.add(d.name));
      } catch { /* ignore read errors */ }
    }
    if (existsSync(tenantSrc)) {
      try {
        readdirSync(tenantSrc, { withFileTypes: true })
          .filter(d => d.isDirectory()).forEach(d => integrations.add(d.name));
      } catch { /* ignore read errors */ }
    }

    for (const integration of integrations) {
      // Skip rx itself and test directories
      if (integration === 'rx' || integration === '__tests__' || integration === 'node_modules') continue;

      const targetDir = join(globalSkillsDir, integration);

      if (existsSync(targetDir)) {
        results.push({
          check: `skills:${integration}`, category: this.category, status: 'pass',
          message: `${integration} skills installed`,
        });
      } else if (!opts.dryRun) {
        const src = existsSync(join(tenantSrc, integration))
          ? join(tenantSrc, integration)
          : join(baseSrc, integration);
        mkdirSync(targetDir, { recursive: true });
        cpSync(src, targetDir, { recursive: true });
        results.push({
          check: `skills:${integration}`, category: this.category, status: 'fixed',
          message: `${integration} skills missing`, action: 'Copied from source',
        });
      } else {
        results.push({
          check: `skills:${integration}`, category: this.category, status: 'fail',
          message: `${integration} skills not installed (dry-run: would copy)`,
        });
      }
    }

    // Check project-level symlinks
    const projectSkillsDir = join(opts.projectRoot, '.claude', 'skills');
    if (existsSync(projectSkillsDir)) {
      results.push({
        check: 'skills:project-symlinks', category: this.category, status: 'pass',
        message: 'Project skills directory present',
      });
    } else if (!opts.dryRun) {
      mkdirSync(join(opts.projectRoot, '.claude'), { recursive: true });
      try {
        symlinkSync(globalSkillsDir, projectSkillsDir);
        results.push({
          check: 'skills:project-symlinks', category: this.category, status: 'fixed',
          message: 'Project skills symlinks missing', action: `Symlinked to ${globalSkillsDir}`,
        });
      } catch {
        results.push({
          check: 'skills:project-symlinks', category: this.category, status: 'fail',
          message: 'Failed to create project skills symlink',
        });
      }
    } else {
      results.push({
        check: 'skills:project-symlinks', category: this.category, status: 'fail',
        message: 'Project skills symlinks missing (dry-run)',
      });
    }

    return results;
  }
}

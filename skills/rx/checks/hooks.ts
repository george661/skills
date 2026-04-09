import { existsSync, readdirSync, readFileSync, writeFileSync, mkdirSync, statSync, chmodSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';
import { Check, CheckResult, RunOpts } from '../types.js';

export class HooksCheck implements Check {
  name = 'hooks';
  category = 'Hooks';

  async run(opts: RunOpts): Promise<CheckResult[]> {
    const results: CheckResult[] = [];
    const targetDir = join(homedir(), '.claude', 'hooks');

    // Discover hook sources
    const baseSrc = join(opts.agentsRoot, 'base', '.claude', 'hooks');
    const tenantSrc = join(opts.agentsRoot, '.claude', 'hooks');

    const sourceFiles = new Map<string, string>();

    const collectFiles = (dir: string) => {
      if (!existsSync(dir)) return;
      try {
        const entries = readdirSync(dir, { withFileTypes: true });
        for (const entry of entries) {
          if (entry.isFile()) {
            sourceFiles.set(entry.name, join(dir, entry.name));
          }
        }
      } catch { /* ignore */ }
    };

    collectFiles(baseSrc);
    collectFiles(tenantSrc); // Tenant overrides base

    if (sourceFiles.size === 0) {
      results.push({
        check: 'hooks:source', category: this.category, status: 'skipped',
        message: 'No hook source files found',
      });
      return results;
    }

    let installed = 0;
    let missing = 0;
    let permFixed = 0;

    for (const [name, srcPath] of sourceFiles) {
      const targetPath = join(targetDir, name);

      if (existsSync(targetPath)) {
        // Check executable permission
        const stat = statSync(targetPath);
        const isExecutable = !!(stat.mode & 0o111);
        if (!isExecutable && !opts.dryRun) {
          chmodSync(targetPath, stat.mode | 0o755);
          permFixed++;
        } else if (!isExecutable) {
          results.push({
            check: `hooks:perm:${name}`, category: this.category, status: 'fail',
            message: `${name} is not executable (dry-run)`,
          });
        }
        installed++;
      } else if (!opts.dryRun) {
        mkdirSync(targetDir, { recursive: true });
        const content = readFileSync(srcPath, 'utf-8');
        writeFileSync(targetPath, content, { mode: 0o755 });
        missing++;
      } else {
        missing++;
      }
    }

    if (missing === 0 && permFixed === 0) {
      results.push({
        check: 'hooks:files', category: this.category, status: 'pass',
        message: `${installed} hook files installed with correct permissions`,
      });
    } else {
      const parts: string[] = [];
      if (missing > 0) parts.push(`${missing} hooks copied`);
      if (permFixed > 0) parts.push(`${permFixed} permissions fixed`);
      results.push({
        check: 'hooks:files', category: this.category,
        status: opts.dryRun ? 'fail' : 'fixed',
        message: missing > 0 ? `${missing} hooks missing` : `${permFixed} hooks had wrong permissions`,
        action: parts.join(', '),
      });
    }

    return results;
  }
}

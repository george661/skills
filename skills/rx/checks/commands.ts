import { existsSync, readdirSync, readFileSync, cpSync, mkdirSync, writeFileSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';
import { Check, CheckResult, RunOpts } from '../types.js';

export class CommandsCheck implements Check {
  name = 'commands';
  category = 'Commands';

  async run(opts: RunOpts): Promise<CheckResult[]> {
    const results: CheckResult[] = [];
    const targetDir = join(homedir(), '.claude', 'commands');

    // Discover command sources
    const baseSrc = join(opts.agentsRoot, 'base', '.claude', 'commands');
    const tenantSrc = join(opts.agentsRoot, '.claude', 'commands');

    // Collect all source commands (tenant overrides base)
    const sourceFiles = new Map<string, string>(); // relativePath -> sourcePath

    const collectFiles = (dir: string, prefix = '') => {
      if (!existsSync(dir)) return;
      try {
        const entries = readdirSync(dir, { withFileTypes: true });
        for (const entry of entries) {
          const relPath = prefix ? `${prefix}/${entry.name}` : entry.name;
          if (entry.isDirectory()) {
            collectFiles(join(dir, entry.name), relPath);
          } else if (entry.name.endsWith('.md')) {
            sourceFiles.set(relPath, join(dir, entry.name));
          }
        }
      } catch { /* ignore read errors */ }
    };

    collectFiles(baseSrc);
    collectFiles(tenantSrc); // Tenant overwrites base entries

    if (sourceFiles.size === 0) {
      results.push({
        check: 'commands:source', category: this.category, status: 'skipped',
        message: 'No command source files found',
      });
      return results;
    }

    let installed = 0;
    let missing = 0;

    for (const [relPath, srcPath] of sourceFiles) {
      const targetPath = join(targetDir, relPath);
      if (existsSync(targetPath)) {
        installed++;
      } else if (!opts.dryRun) {
        const dir = join(targetDir, relPath.includes('/') ? relPath.split('/').slice(0, -1).join('/') : '');
        mkdirSync(dir, { recursive: true });
        const content = readFileSync(srcPath, 'utf-8');
        writeFileSync(targetPath, content);
        missing++;
      } else {
        missing++;
      }
    }

    if (missing === 0) {
      results.push({
        check: 'commands:files', category: this.category, status: 'pass',
        message: `${installed} command files installed`,
      });
    } else if (!opts.dryRun) {
      results.push({
        check: 'commands:files', category: this.category, status: 'fixed',
        message: `${missing} command files were missing`,
        action: `Copied ${missing} files from source`,
      });
    } else {
      results.push({
        check: 'commands:files', category: this.category, status: 'fail',
        message: `${missing} command files missing (dry-run)`,
      });
    }

    return results;
  }
}

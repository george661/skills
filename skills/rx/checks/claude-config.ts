import { existsSync, mkdirSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';
import { Check, CheckResult, RunOpts } from '../types.js';
import { loadJsonConfig } from '../rx-client.js';

export class ClaudeConfigCheck implements Check {
  name = 'claude-config';
  category = 'Claude Config';

  async run(opts: RunOpts): Promise<CheckResult[]> {
    const results: CheckResult[] = [];
    const claudeDir = join(homedir(), '.claude');

    // Check global directories
    const requiredDirs = [
      { path: join(claudeDir, 'commands'), label: '~/.claude/commands' },
      { path: join(claudeDir, 'hooks'), label: '~/.claude/hooks' },
      { path: join(claudeDir, 'skills'), label: '~/.claude/skills' },
      { path: join(claudeDir, 'rx'), label: '~/.claude/rx' },
    ];

    for (const dir of requiredDirs) {
      if (existsSync(dir.path)) {
        results.push({
          check: `claude-config:dir:${dir.label}`, category: this.category, status: 'pass',
          message: `${dir.label} exists`,
        });
      } else if (!opts.dryRun) {
        mkdirSync(dir.path, { recursive: true });
        results.push({
          check: `claude-config:dir:${dir.label}`, category: this.category, status: 'fixed',
          message: `${dir.label} missing`, action: 'Created directory',
        });
      } else {
        results.push({
          check: `claude-config:dir:${dir.label}`, category: this.category, status: 'fail',
          message: `${dir.label} missing (dry-run)`,
        });
      }
    }

    // Check global settings.json
    const globalSettings = join(claudeDir, 'settings.json');
    const settings = loadJsonConfig<Record<string, unknown>>(globalSettings);
    if (settings) {
      results.push({
        check: 'claude-config:global-settings', category: this.category, status: 'pass',
        message: '~/.claude/settings.json exists and valid',
      });
    } else {
      results.push({
        check: 'claude-config:global-settings', category: this.category, status: 'fail',
        message: '~/.claude/settings.json missing or invalid',
        error: 'Create ~/.claude/settings.json with valid JSON',
      });
    }

    // Check project directories
    const projectDirs = [
      { path: join(opts.projectRoot, '.claude'), label: '$PROJECT_ROOT/.claude' },
      { path: join(opts.projectRoot, '.claude', 'commands'), label: '$PROJECT_ROOT/.claude/commands' },
      { path: join(opts.projectRoot, '.claude', 'skills'), label: '$PROJECT_ROOT/.claude/skills' },
    ];

    for (const dir of projectDirs) {
      if (existsSync(dir.path)) {
        results.push({
          check: `claude-config:dir:${dir.label}`, category: this.category, status: 'pass',
          message: `${dir.label} exists`,
        });
      } else if (!opts.dryRun) {
        mkdirSync(dir.path, { recursive: true });
        results.push({
          check: `claude-config:dir:${dir.label}`, category: this.category, status: 'fixed',
          message: `${dir.label} missing`, action: 'Created directory',
        });
      } else {
        results.push({
          check: `claude-config:dir:${dir.label}`, category: this.category, status: 'fail',
          message: `${dir.label} missing (dry-run)`,
        });
      }
    }

    return results;
  }
}

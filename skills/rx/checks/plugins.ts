import { Check, CheckResult, RunOpts, Plugin } from '../types.js';
import { exec, loadJsonConfig } from '../rx-client.js';
import { join } from 'path';
import { existsSync, readdirSync } from 'fs';
import { homedir } from 'os';

export class PluginsCheck implements Check {
  name = 'plugins';
  category = 'Plugins';

  async run(opts: RunOpts): Promise<CheckResult[]> {
    const results: CheckResult[] = [];
    const plugins = loadJsonConfig<Plugin[]>(
      join(opts.agentsRoot, 'config', 'plugins.json')
    ) ?? [];

    if (plugins.length === 0) {
      results.push({
        check: 'plugins:config', category: this.category, status: 'skipped',
        message: 'No plugins configured (config/plugins.json missing)',
      });
      return results;
    }

    // Prefer CLI detection over cache directory inspection
    const cliList = exec('claude plugins list 2>/dev/null');
    let installedPlugins: string[] = [];

    if (cliList.ok) {
      installedPlugins = cliList.stdout.split('\n').map(l => l.trim()).filter(Boolean);
    } else {
      // Fallback: inspect cache directory
      const pluginsCache = join(homedir(), '.claude', 'plugins', 'cache');
      if (existsSync(pluginsCache)) {
        try {
          installedPlugins = readdirSync(pluginsCache).flatMap(marketplace => {
            const mDir = join(pluginsCache, marketplace);
            try {
              return readdirSync(mDir).map(name => `${name}@${marketplace}`);
            } catch {
              return [];
            }
          });
        } catch { /* ignore */ }
      }
    }

    for (const plugin of plugins) {
      const identifier = `${plugin.name}@${plugin.marketplace}`;
      const isInstalled = installedPlugins.some(d =>
        d.startsWith(`${plugin.name}@${plugin.marketplace}`) || d.includes(plugin.name)
      );

      if (isInstalled) {
        results.push({
          check: `plugins:${plugin.name}`, category: this.category, status: 'pass',
          message: `${plugin.name} (${plugin.marketplace})`,
        });
      } else if (!opts.dryRun) {
        const install = exec(`claude plugins add "${identifier}"`, { timeout: 60000 });
        results.push({
          check: `plugins:${plugin.name}`, category: this.category,
          status: install.ok ? 'fixed' : (plugin.required ? 'fail' : 'skipped'),
          message: `${plugin.name} not installed`,
          ...(install.ok ? { action: `claude plugins add ${identifier}` } : { error: install.stderr }),
        });
      } else {
        results.push({
          check: `plugins:${plugin.name}`, category: this.category,
          status: plugin.required ? 'fail' : 'skipped',
          message: `${plugin.name} not installed (dry-run)`,
        });
      }
    }

    return results;
  }
}

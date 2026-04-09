import { Check, CheckResult, RunOpts, BrewPackage } from '../types.js';
import { exec, loadJsonConfig } from '../rx-client.js';
import { join } from 'path';

export class BrewCheck implements Check {
  name = 'brew';
  category = 'Brew Packages';

  async run(opts: RunOpts): Promise<CheckResult[]> {
    const results: CheckResult[] = [];

    const tenantPkgs = loadJsonConfig<BrewPackage[]>(
      join(opts.agentsRoot, 'config', 'brew-packages.json')
    ) ?? [];

    const packages = tenantPkgs;

    if (packages.length === 0) {
      results.push({
        check: 'brew:config', category: this.category, status: 'skipped',
        message: 'No brew packages configured',
      });
      return results;
    }

    for (const pkg of packages) {
      const installed = exec(`brew list ${pkg.name} 2>/dev/null`);

      if (installed.ok) {
        const ver = pkg.version_command ? exec(pkg.version_command) : null;
        results.push({
          check: `brew:${pkg.name}`, category: this.category, status: 'pass',
          message: `${pkg.name}${ver?.ok ? ` ${ver.stdout.split('\n')[0]}` : ''}`,
        });
      } else if (!opts.dryRun) {
        const install = exec(`brew install ${pkg.name}`, { timeout: 300000 });
        results.push({
          check: `brew:${pkg.name}`, category: this.category,
          status: install.ok ? 'fixed' : (pkg.required ? 'fail' : 'skipped'),
          message: `${pkg.name} not installed`,
          ...(install.ok ? { action: `brew install ${pkg.name}` } : { error: `Failed to install: ${install.stderr}` }),
        });
      } else {
        results.push({
          check: `brew:${pkg.name}`, category: this.category,
          status: pkg.required ? 'fail' : 'skipped',
          message: `${pkg.name} not installed (dry-run: would brew install)`,
        });
      }
    }

    return results;
  }
}

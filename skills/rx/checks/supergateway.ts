import { Check, CheckResult, RunOpts } from '../types.js';
import { exec, loadJsonConfig } from '../rx-client.js';
import { join } from 'path';
import { existsSync } from 'fs';
import { homedir } from 'os';

interface SupergatewayConfig {
  servers: Record<string, { command: string; port: number; scope: string; description: string }>;
}

export class SupergatewayCheck implements Check {
  name = 'supergateway';
  category = 'Supergateway';

  async run(opts: RunOpts): Promise<CheckResult[]> {
    const results: CheckResult[] = [];
    const configPath = join(opts.agentsRoot, 'supergateway', 'config.json');
    const config = loadJsonConfig<SupergatewayConfig>(configPath);

    if (!config) {
      results.push({
        check: 'supergateway:config', category: this.category, status: 'fail',
        message: 'supergateway/config.json not found or invalid',
      });
      return results;
    }

    const servers = Object.entries(config.servers ?? {});
    if (servers.length === 0) {
      results.push({
        check: 'supergateway:config', category: this.category, status: 'skipped',
        message: 'No supergateway servers configured',
      });
      return results;
    }

    for (const [name, server] of servers) {
      const portCheck = exec(`lsof -i :${server.port} -sTCP:LISTEN -t`);
      if (portCheck.ok && portCheck.stdout.trim()) {
        results.push({
          check: `supergateway:${name}`, category: this.category, status: 'pass',
          message: `${name} listening on port ${server.port}`,
        });
      } else if (!opts.dryRun) {
        const startScript = join(homedir(), '.claude', 'supergateway', 'start.sh');
        if (existsSync(startScript)) {
          const start = exec(`bash "${startScript}" ${name}`);
          results.push({
            check: `supergateway:${name}`, category: this.category,
            status: start.ok ? 'fixed' : 'fail',
            message: `${name} not running on port ${server.port}`,
            ...(start.ok ? { action: 'Started via start.sh' } : { error: start.stderr }),
          });
        } else {
          results.push({
            check: `supergateway:${name}`, category: this.category, status: 'fail',
            message: `${name} not running, start.sh not found`,
          });
        }
      } else {
        results.push({
          check: `supergateway:${name}`, category: this.category, status: 'fail',
          message: `${name} not running on port ${server.port} (dry-run)`,
        });
      }
    }

    // Check launchd plist
    const plistPath = join(homedir(), 'Library', 'LaunchAgents', 'com.base.supergateway.plist');
    if (existsSync(plistPath)) {
      const loaded = exec('launchctl list | grep com.base.supergateway');
      results.push({
        check: 'supergateway:launchd', category: this.category,
        status: loaded.ok ? 'pass' : 'skipped',
        message: loaded.ok ? 'LaunchAgent loaded' : 'LaunchAgent plist exists but not loaded',
      });
    }

    return results;
  }
}

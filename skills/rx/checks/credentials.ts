import { Check, CheckResult, RunOpts } from '../types.js';
import { exec, loadJsonConfig } from '../rx-client.js';
import { join } from 'path';
import { migrate } from '../migrate-credentials.js';

export class CredentialsCheck implements Check {
  name = 'credentials';
  category = 'Credentials';

  async run(opts: RunOpts): Promise<CheckResult[]> {
    const results: CheckResult[] = [];
    const credsPath = join(opts.projectRoot, '.claude', 'credentials.json');
    const raw = loadJsonConfig<Record<string, unknown>>(credsPath) ?? {};
    // Support both flat format { jira: {...} } and wrapped { credentials: { jira: {...} } }
    const creds = ((raw.credentials ?? raw) as Record<string, Record<string, string>>);

    // Auto-migrate if no project credentials exist
    if (!creds || Object.keys(creds).length === 0) {
      const { migrated, skipped } = migrate(opts.projectRoot, opts.dryRun);
      for (const service of migrated) {
        results.push({
          check: `credentials:migrate-${service}`,
          category: this.category,
          status: opts.dryRun ? 'fail' : 'fixed',
          message: `${service} credentials migrated to project credentials.json`,
          action: opts.dryRun ? undefined : 'Copied from .env / global settings',
        });
      }
      // Reload credentials after migration
      if (migrated.length > 0 && !opts.dryRun) {
        const reloadedRaw = loadJsonConfig<Record<string, unknown>>(credsPath);
        if (reloadedRaw) {
          const reloaded = (reloadedRaw.credentials ?? reloadedRaw) as Record<string, Record<string, string>>;
          Object.assign(creds, reloaded);
        }
      }
    }

    // Jira
    const jira = creds.jira;
    if (jira?.host && jira?.username && jira?.apiToken) {
      try {
        const auth = Buffer.from(`${jira.username}:${jira.apiToken}`).toString('base64');
        const resp = await fetch(`https://${jira.host}/rest/api/3/myself`, {
          headers: { 'Authorization': `Basic ${auth}`, 'Accept': 'application/json' },
          signal: AbortSignal.timeout(15000),
        });
        results.push({
          check: 'credentials:jira', category: this.category,
          status: resp.ok ? 'pass' : 'fail',
          message: resp.ok ? `Jira (${jira.host})` : 'Jira credentials invalid',
          ...(!resp.ok && { error: `HTTP ${resp.status}. Create token at https://id.atlassian.com/manage-profile/security/api-tokens` }),
        });
      } catch (e) {
        results.push({
          check: 'credentials:jira', category: this.category, status: 'fail',
          message: 'Jira unreachable', error: e instanceof Error ? e.message : String(e),
        });
      }
    } else {
      results.push({
        check: 'credentials:jira', category: this.category, status: 'fail',
        message: 'Jira credentials not found in project credentials.json',
        error: 'Add jira credentials to $PROJECT_ROOT/.claude/credentials.json',
      });
    }

    // Bitbucket
    const bb = creds.bitbucket;
    if (bb?.workspace && bb?.username && bb?.token) {
      try {
        const auth = Buffer.from(`${bb.username}:${bb.token}`).toString('base64');
        const resp = await fetch('https://api.bitbucket.org/2.0/user', {
          headers: { 'Authorization': `Basic ${auth}` },
          signal: AbortSignal.timeout(15000),
        });
        results.push({
          check: 'credentials:bitbucket', category: this.category,
          status: resp.ok ? 'pass' : 'fail',
          message: resp.ok ? `Bitbucket (${bb.workspace})` : 'Bitbucket credentials invalid',
          ...(!resp.ok && { error: `HTTP ${resp.status}. Create app password at https://bitbucket.org/account/settings/app-passwords/` }),
        });
      } catch (e) {
        results.push({
          check: 'credentials:bitbucket', category: this.category, status: 'fail',
          message: 'Bitbucket unreachable', error: e instanceof Error ? e.message : String(e),
        });
      }
    } else {
      results.push({
        check: 'credentials:bitbucket', category: this.category, status: 'fail',
        message: 'Bitbucket credentials not found in project credentials.json',
      });
    }

    // AgentDB
    const adb = creds.agentdb;
    if (adb?.apiKey && adb?.url) {
      try {
        const resp = await fetch(`${adb.url}/api/v1/db/health`, {
          headers: { 'X-Api-Key': adb.apiKey },
          signal: AbortSignal.timeout(10000),
        });
        results.push({
          check: 'credentials:agentdb', category: this.category,
          status: resp.ok ? 'pass' : 'fail',
          message: resp.ok ? 'AgentDB reachable' : 'AgentDB unreachable',
        });
      } catch {
        results.push({
          check: 'credentials:agentdb', category: this.category, status: 'fail',
          message: 'AgentDB unreachable',
        });
      }
    } else {
      results.push({
        check: 'credentials:agentdb', category: this.category, status: 'fail',
        message: 'AgentDB credentials not configured',
      });
    }

    // Slack (just check presence)
    const slack = creds.slack;
    results.push({
      check: 'credentials:slack', category: this.category,
      status: slack?.botToken ? 'pass' : 'skipped',
      message: slack?.botToken ? 'Slack bot token configured' : 'Slack not configured (optional)',
    });

    // AWS profiles
    const awsProfiles = (process.env.AWS_CHECK_PROFILES || 'your-dev-profile,your-demo-profile,your-prod-profile').split(',').map(p => p.trim()).filter(Boolean);
    const primaryProfile = awsProfiles[0] || 'your-dev-profile';
    for (const profile of awsProfiles) {
      const sts = exec(`aws sts get-caller-identity --profile ${profile} 2>&1`, { timeout: 15000 });
      results.push({
        check: `credentials:aws-${profile}`, category: this.category,
        status: sts.ok ? 'pass' : (profile === primaryProfile ? 'fail' : 'skipped'),
        message: sts.ok ? `AWS ${profile}` : `AWS ${profile} not configured`,
        ...((!sts.ok && profile === primaryProfile) && {
          error: `Run: aws sso login --profile ${profile}`,
        }),
      });
    }

    return results;
  }
}

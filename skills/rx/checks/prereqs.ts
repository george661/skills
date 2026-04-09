import { Check, CheckResult, RunOpts } from '../types.js';
import { exec } from '../rx-client.js';

export class PrereqsCheck implements Check {
  name = 'prereqs';
  category = 'Prerequisites';

  async run(opts: RunOpts): Promise<CheckResult[]> {
    const results: CheckResult[] = [];

    // Node.js 18+
    const node = exec('node --version');
    if (node.ok) {
      const version = parseInt(node.stdout.replace('v', '').split('.')[0], 10);
      results.push({
        check: 'prereqs:node',
        category: this.category,
        status: version >= 18 ? 'pass' : 'fail',
        message: version >= 18 ? `node ${node.stdout}` : `node ${node.stdout} (need v18+)`,
        ...(version < 18 && { error: 'Upgrade Node.js to v18 or later' }),
      });
    } else {
      results.push({
        check: 'prereqs:node', category: this.category, status: 'fail',
        message: 'node not found', error: 'Install Node.js 18+ from https://nodejs.org',
      });
    }

    // npx
    const npx = exec('npx --version');
    results.push({
      check: 'prereqs:npx', category: this.category,
      status: npx.ok ? 'pass' : 'fail',
      message: npx.ok ? `npx ${npx.stdout}` : 'npx not found',
      ...((!npx.ok) && { error: 'npx should come with Node.js. Reinstall Node.' }),
    });

    // git
    const git = exec('git --version');
    results.push({
      check: 'prereqs:git', category: this.category,
      status: git.ok ? 'pass' : 'fail',
      message: git.ok ? `git ${git.stdout.replace('git version ', '')}` : 'git not found',
      ...((!git.ok) && { error: 'Install git: brew install git' }),
    });

    // aws-cli
    const aws = exec('aws --version');
    if (aws.ok) {
      results.push({
        check: 'prereqs:aws-cli', category: this.category, status: 'pass',
        message: `aws-cli ${aws.stdout.split(' ')[0]?.replace('aws-cli/', '') ?? aws.stdout}`,
      });
    } else if (!opts.dryRun) {
      const install = exec('brew install awscli', { timeout: 120000 });
      results.push({
        check: 'prereqs:aws-cli', category: this.category,
        status: install.ok ? 'fixed' : 'fail',
        message: 'aws-cli not found',
        ...(install.ok ? { action: 'brew install awscli' } : { error: 'Failed to install awscli via brew' }),
      });
    } else {
      results.push({
        check: 'prereqs:aws-cli', category: this.category, status: 'fail',
        message: 'aws-cli not found (dry-run: would brew install awscli)',
      });
    }

    // claude CLI
    const claude = exec('claude --version');
    results.push({
      check: 'prereqs:claude-cli', category: this.category,
      status: claude.ok ? 'pass' : 'fail',
      message: claude.ok ? `claude ${claude.stdout}` : 'claude CLI not found',
      ...((!claude.ok) && { error: 'Install: npm install -g @anthropic-ai/claude-code' }),
    });

    // SSH connectivity for Bitbucket
    const ssh = exec('ssh -T git@bitbucket.org 2>&1', { timeout: 15000 });
    // Bitbucket returns exit code 0 with a welcome message on success
    const sshOk = ssh.ok || ssh.stderr.includes('logged in as');
    results.push({
      check: 'prereqs:ssh-bitbucket', category: this.category,
      status: sshOk ? 'pass' : 'fail',
      message: sshOk ? 'SSH access to Bitbucket' : 'SSH access to Bitbucket failed',
      ...(!sshOk && { error: 'Configure SSH key: https://bitbucket.org/account/settings/ssh-keys/' }),
    });

    // git user.name and user.email
    const gitName = exec('git config user.name');
    const gitEmail = exec('git config user.email');
    results.push({
      check: 'prereqs:git-user', category: this.category,
      status: gitName.ok && gitEmail.ok ? 'pass' : 'fail',
      message: gitName.ok && gitEmail.ok
        ? `git user: ${gitName.stdout} <${gitEmail.stdout}>`
        : 'git user.name or user.email not configured',
      ...(!gitName.ok && { error: 'Run: git config --global user.name "Your Name"' }),
    });

    // Platform check (macOS required)
    const platform = process.platform;
    results.push({
      check: 'prereqs:platform', category: this.category,
      status: platform === 'darwin' ? 'pass' : 'fail',
      message: platform === 'darwin' ? 'macOS detected' : `${platform} detected (macOS required)`,
      ...(platform !== 'darwin' && { error: 'rx is designed for macOS. Some checks will not work on other platforms.' }),
    });

    // PATH includes Homebrew
    const path = process.env.PATH ?? '';
    const hasBrewPath = path.includes('/opt/homebrew/bin') || path.includes('/usr/local/bin');
    results.push({
      check: 'prereqs:path-homebrew', category: this.category,
      status: hasBrewPath ? 'pass' : 'fail',
      message: hasBrewPath ? 'Homebrew in PATH' : 'Homebrew bin directory not in PATH',
      ...(!hasBrewPath && { error: 'Add /opt/homebrew/bin to PATH in your shell profile' }),
    });

    return results;
  }
}

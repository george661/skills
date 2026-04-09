#!/usr/bin/env npx tsx
// login - Login to a Concourse target using AWS secret, env vars, or browser auth.
import { execSync } from 'child_process';
import { getFlyCredentials } from './fly-client.js';

interface Input {
  target?: string;
  url?: string;
  username?: string;
  password?: string;
}

async function execute(input: Input) {
  const creds = getFlyCredentials();

  const target = input.target ?? creds.target;
  const url = input.url ?? creds.url;
  const username = input.username ?? creds.username;
  const password = input.password ?? creds.password;

  if (!target || !url) {
    throw new Error(
      'Missing required credentials. Provide target and url ' +
      'as parameters or configure them via AWS Secrets Manager, environment variables, .env, or settings.json.'
    );
  }

  let loginCmd: string;
  let authMethod: string;

  if (username && password) {
    loginCmd = `fly -t ${target} login -c ${url} -u ${username} -p ${password}`;
    authMethod = 'username/password';
  } else {
    loginCmd = `fly -t ${target} login -c ${url} -b`;
    authMethod = 'browser';
  }

  try {
    execSync(loginCmd, { stdio: 'inherit', timeout: 120000 });
    return {
      success: true,
      target,
      url,
      authMethod,
      message: `Logged in to target "${target}" at ${url} via ${authMethod} authentication`,
    };
  } catch (err) {
    if (err && typeof err === 'object' && 'stderr' in err) {
      const stderr = (err as { stderr: Buffer }).stderr.toString().trim();
      throw new Error(`Login failed: ${stderr || String(err)}`);
    }
    throw new Error(`Login failed: ${err instanceof Error ? err.message : String(err)}`);
  }
}

const input = JSON.parse(process.argv[2] || '{}') as Input;
execute(input).then(r => console.log(JSON.stringify(r, null, 2))).catch(e => { console.error(e.message); process.exit(1); });

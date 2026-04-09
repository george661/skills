#!/usr/bin/env node
/**
 * Get a Cognito JWT token via SRP auth.
 *
 * Usage:
 *   node cognito-srp-token.js <email> <password> [env]
 *   node cognito-srp-token.js testuser@mail.dev.example.com TestUser123! dev
 *
 * Outputs the IdToken JWT to stdout. Errors go to stderr.
 *
 * Requires: amazon-cognito-identity-js (available in sdk/node_modules)
 *
 * Environment configs:
 *   dev:  UserPoolId=us-east-1_yMqRDIh9x, ClientId=54bui8nt8qf87f9reqfh355the (oauth-test-cli, no secret, SRP)
 *   demo: Resolved from SSM /auth-service/cognito/user-pool-id and /auth-service/cognito/client-id
 */

const path = require('path');

// Resolve amazon-cognito-identity-js from sdk (always available)
function _findProjectRoot() {
  // 1. Explicit env vars (set by dispatch-local.py, tenant.env, etc.)
  for (const k of ['WORKSPACE_ROOT', 'PROJECT_ROOT']) {
    const v = (process.env[k] || '').replace(/\/+$/, '');
    if (v && require('fs').existsSync(path.join(v, '.git'))) return v;
  }
  // 2. Walk up from cwd looking for a directory that contains sdk/
  let dir = process.cwd();
  while (dir !== path.dirname(dir)) {
    if (require('fs').existsSync(path.join(dir, '.git'))) return dir;
    dir = path.dirname(dir);
  }
  // 3. Last resort: common workspace layouts under $HOME
  const home = require('os').homedir();
  for (const rel of ['dev/workspace', 'projects/workspace', 'workspace']) {
    const candidate = path.join(home, rel);
    if (require('fs').existsSync(path.join(candidate, '.git'))) return candidate;
  }
  throw new Error('Cannot find project root. Set WORKSPACE_ROOT or PROJECT_ROOT, or run from within the project workspace.');
}
const _projectRoot = _findProjectRoot();
const _cognitoModuleDir = process.env.COGNITO_MODULE_DIR || path.resolve(_projectRoot, 'node_modules');
const cognitoIdpPath = path.resolve(_cognitoModuleDir, 'amazon-cognito-identity-js');
const AmazonCognitoIdentity = require(cognitoIdpPath);

// node-fetch for Node <18
try { global.fetch = require(path.resolve(_cognitoModuleDir, 'node-fetch')); } catch (_) {}

const ENV_CONFIG = {
  dev: {
    UserPoolId: 'us-east-1_yMqRDIh9x',
    ClientId: '54bui8nt8qf87f9reqfh355the',
  },
  // demo/prod: add when needed or resolve from SSM
};

const [,, email, password, env = 'dev'] = process.argv;

if (!email || !password) {
  process.stderr.write('Usage: node cognito-srp-token.js <email> <password> [env]\n');
  process.exit(1);
}

const config = ENV_CONFIG[env];
if (!config) {
  process.stderr.write(`Unknown env: ${env}. Available: ${Object.keys(ENV_CONFIG).join(', ')}\n`);
  process.exit(1);
}

const userPool = new AmazonCognitoIdentity.CognitoUserPool(config);
const authDetails = new AmazonCognitoIdentity.AuthenticationDetails({ Username: email, Password: password });
const cognitoUser = new AmazonCognitoIdentity.CognitoUser({ Username: email, Pool: userPool });

cognitoUser.authenticateUser(authDetails, {
  onSuccess: (result) => {
    process.stdout.write(result.getIdToken().getJwtToken());
    process.exit(0);
  },
  onFailure: (err) => {
    process.stderr.write('SRP_AUTH_ERROR: ' + err.message + '\n');
    process.exit(1);
  },
});

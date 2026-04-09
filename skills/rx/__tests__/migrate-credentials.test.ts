import { describe, it, expect } from 'vitest';
import { extractCredentialsFromEnv, mergeIntoSettings } from '../migrate-credentials.js';

describe('extractCredentialsFromEnv', () => {
  it('extracts jira credentials from env content', () => {
    const envContent = `
JIRA_HOST=your-org.atlassian.net
JIRA_USERNAME=user@example.com
JIRA_API_TOKEN=secret123
OTHER_VAR=keepme
`;
    const creds = extractCredentialsFromEnv(envContent);
    expect(creds.jira).toEqual({
      host: 'your-org.atlassian.net',
      username: 'user@example.com',
      apiToken: 'secret123',
    });
  });

  it('extracts bitbucket credentials from env content', () => {
    const envContent = `
BITBUCKET_WORKSPACE=your-org
BITBUCKET_USERNAME=user@example.com
BITBUCKET_TOKEN=bbtoken
`;
    const creds = extractCredentialsFromEnv(envContent);
    expect(creds.bitbucket).toEqual({
      workspace: 'your-org',
      username: 'user@example.com',
      token: 'bbtoken',
      default_branch: 'main',
    });
  });
});

describe('mergeIntoSettings', () => {
  it('merges credentials into existing settings', () => {
    const existing = { permissions: { allow: [] } };
    const creds = { jira: { host: 'x', username: 'y', apiToken: 'z' } };
    const result = mergeIntoSettings(existing, creds);
    expect(result.permissions).toEqual({ allow: [] });
    expect(result.credentials.jira).toEqual(creds.jira);
  });

  it('does not overwrite existing credentials', () => {
    const existing = { credentials: { jira: { host: 'existing' } } };
    const creds = { jira: { host: 'new', username: 'y', apiToken: 'z' } };
    const result = mergeIntoSettings(existing, creds);
    expect(result.credentials.jira?.host).toBe('existing');
  });
});

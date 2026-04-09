import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { resolveIssueProvider, translateParams } from '../issues-router.js';

describe('resolveIssueProvider', () => {
  const origEnv = process.env.ISSUE_TRACKER;

  afterEach(() => {
    if (origEnv === undefined) {
      delete process.env.ISSUE_TRACKER;
    } else {
      process.env.ISSUE_TRACKER = origEnv;
    }
  });

  it('returns jira when ISSUE_TRACKER is unset', () => {
    delete process.env.ISSUE_TRACKER;
    expect(resolveIssueProvider()).toBe('jira');
  });

  it('returns github when ISSUE_TRACKER=github', () => {
    process.env.ISSUE_TRACKER = 'github';
    expect(resolveIssueProvider()).toBe('github');
  });

  it('returns linear when ISSUE_TRACKER=linear', () => {
    process.env.ISSUE_TRACKER = 'linear';
    expect(resolveIssueProvider()).toBe('linear');
  });

  it('returns github when explicit override is github', () => {
    delete process.env.ISSUE_TRACKER;
    expect(resolveIssueProvider('github')).toBe('github');
  });
});

describe('translateParams', () => {
  it('jira get_issue passes through unchanged', () => {
    const params = { issue_key: 'PROJ-1' };
    expect(translateParams('jira', 'get_issue', params)).toEqual({ issue_key: 'PROJ-1' });
  });

  it('github get_issue parses owner/repo#N', () => {
    const params = { issue_key: 'org/repo#42' };
    expect(translateParams('github', 'get_issue', params)).toEqual({
      owner: 'org',
      repo: 'repo',
      issue_number: 42,
    });
  });

  it('linear get_issue maps to identifier', () => {
    const params = { issue_key: 'PROJ-1' };
    expect(translateParams('linear', 'get_issue', params)).toEqual({ identifier: 'PROJ-1' });
  });

  it('github create_issue parses project_key into owner/repo', () => {
    const params = { project_key: 'org/repo' };
    expect(translateParams('github', 'create_issue', params)).toEqual({
      owner: 'org',
      repo: 'repo',
    });
  });
});

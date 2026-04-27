import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { resolveIssueProvider, translateParams, translateLinearParams } from '../issues-router.js';

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

describe('translateLinearParams', () => {
  it('transition_issue maps transition_id to stateId', () => {
    const params = { issue_key: 'PROJ-1', transition_id: 'state-uuid-123' };
    const result = translateLinearParams('transition_issue', params);
    expect(result).toEqual({
      identifier: 'PROJ-1',
      stateId: 'state-uuid-123',
    });
    expect(result.transition_id).toBeUndefined();
  });

  it('search_issues with JQL project=KEY translates to Linear filter', () => {
    const params = { jql: 'project = PROJ' };
    const result = translateLinearParams('search_issues', params);
    expect(result.filter).toEqual({ team: { key: { eq: 'PROJ' } } });
    expect(result.jql).toBeUndefined();
  });

  it('search_issues with JQL status="Name" translates to Linear filter', () => {
    const params = { jql: 'status = "In Progress"' };
    const result = translateLinearParams('search_issues', params);
    expect(result.filter).toEqual({ state: { name: { eq: 'In Progress' } } });
  });

  it('search_issues with JQL AND combination translates correctly', () => {
    const params = { jql: 'project = PROJ AND status = "Done"' };
    const result = translateLinearParams('search_issues', params);
    expect(result.filter).toEqual({
      team: { key: { eq: 'PROJ' } },
      state: { name: { eq: 'Done' } },
    });
  });

  it('search_issues with native filter passes through unchanged', () => {
    const params = { filter: { team: { key: { eq: 'KEY' } } } };
    const result = translateLinearParams('search_issues', params);
    expect(result.filter).toEqual({ team: { key: { eq: 'KEY' } } });
  });

  it('search_issues with unsupported JQL currentUser() throws', () => {
    const params = { jql: 'assignee = currentUser()' };
    expect(() => translateLinearParams('search_issues', params)).toThrow(
      /Unsupported JQL syntax.*currentUser/
    );
  });

  it('search_issues with unsupported JQL ORDER BY throws', () => {
    const params = { jql: 'project = PROJ ORDER BY created DESC' };
    expect(() => translateLinearParams('search_issues', params)).toThrow(
      /Unsupported JQL syntax.*ORDER BY/
    );
  });
});

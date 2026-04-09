/**
 * Tests for jiraUpload in jira-client.ts
 *
 * Validates multipart/form-data upload with correct headers and URL construction.
 * Mocks fetch and fs/promises to avoid real API calls and file system access.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock fs/promises before importing the module under test
vi.mock('fs/promises', () => ({
  readFile: vi.fn().mockResolvedValue(Buffer.from('fake-file-content')),
}));

// Mock fs (sync) for credential loading
vi.mock('fs', () => ({
  readFileSync: vi.fn().mockReturnValue(''),
  existsSync: vi.fn().mockReturnValue(false),
}));

// Store original fetch
const originalFetch = globalThis.fetch;

describe('jiraUpload', () => {
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    // Set environment variables for credentials
    process.env.JIRA_HOST = 'test.atlassian.net';
    process.env.JIRA_USERNAME = 'test@example.com';
    process.env.JIRA_API_TOKEN = 'test-token';

    // Mock global fetch
    mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve([{ id: '12345', filename: 'screenshot.png', self: 'https://test.atlassian.net/rest/api/2/attachment/12345' }]),
    });
    globalThis.fetch = mockFetch as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    delete process.env.JIRA_HOST;
    delete process.env.JIRA_USERNAME;
    delete process.env.JIRA_API_TOKEN;
    vi.restoreAllMocks();
  });

  it('constructs the correct URL with issue key', async () => {
    const { jiraUpload } = await import('../jira-client.js');
    await jiraUpload('PROJ-123', '/tmp/screenshot.png', 'screenshot.png');

    expect(mockFetch).toHaveBeenCalledOnce();
    const [url] = mockFetch.mock.calls[0];
    expect(url).toBe('https://test.atlassian.net/rest/api/2/issue/PROJ-123/attachments');
  });

  it('sets X-Atlassian-Token: no-check header', async () => {
    const { jiraUpload } = await import('../jira-client.js');
    await jiraUpload('PROJ-123', '/tmp/screenshot.png', 'screenshot.png');

    const [, options] = mockFetch.mock.calls[0];
    expect(options.headers['X-Atlassian-Token']).toBe('no-check');
  });

  it('sets Authorization header with Basic auth', async () => {
    const { jiraUpload } = await import('../jira-client.js');
    await jiraUpload('PROJ-123', '/tmp/screenshot.png', 'screenshot.png');

    const [, options] = mockFetch.mock.calls[0];
    const expectedAuth = Buffer.from('test@example.com:test-token').toString('base64');
    expect(options.headers['Authorization']).toBe(`Basic ${expectedAuth}`);
  });

  it('does NOT set Content-Type header (lets fetch handle multipart boundary)', async () => {
    const { jiraUpload } = await import('../jira-client.js');
    await jiraUpload('PROJ-123', '/tmp/screenshot.png', 'screenshot.png');

    const [, options] = mockFetch.mock.calls[0];
    expect(options.headers['Content-Type']).toBeUndefined();
  });

  it('uses FormData as the request body', async () => {
    const { jiraUpload } = await import('../jira-client.js');
    await jiraUpload('PROJ-123', '/tmp/screenshot.png', 'screenshot.png');

    const [, options] = mockFetch.mock.calls[0];
    expect(options.body).toBeInstanceOf(FormData);
  });

  it('uses POST method', async () => {
    const { jiraUpload } = await import('../jira-client.js');
    await jiraUpload('PROJ-123', '/tmp/screenshot.png', 'screenshot.png');

    const [, options] = mockFetch.mock.calls[0];
    expect(options.method).toBe('POST');
  });

  it('defaults filename to basename of file_path when not provided', async () => {
    const { jiraUpload } = await import('../jira-client.js');
    await jiraUpload('PROJ-123', '/tmp/my-evidence.png');

    const [, options] = mockFetch.mock.calls[0];
    const formData = options.body as FormData;
    const file = formData.get('file') as File;
    expect(file.name).toBe('my-evidence.png');
  });

  it('throws on non-OK response', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 403,
      text: () => Promise.resolve('Forbidden'),
    });

    const { jiraUpload } = await import('../jira-client.js');
    await expect(jiraUpload('PROJ-123', '/tmp/screenshot.png', 'screenshot.png'))
      .rejects.toThrow('Jira upload failed: 403 Forbidden');
  });
});

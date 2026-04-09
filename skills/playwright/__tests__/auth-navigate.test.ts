/**
 * Tests for auth-navigate.ts utility script
 *
 * Validates input validation and error handling for auth-navigate.
 * Does NOT test actual browser login (requires live auth page).
 * Uses execSync to invoke the script as a separate process (matching existing test pattern).
 */

import { describe, it, expect } from 'vitest';
import { execSync } from 'child_process';
import { resolve } from 'path';

const SCRIPT_PATH = resolve(__dirname, '..', 'auth-navigate.ts');

function run(input?: string): { stdout: string; exitCode: number } {
  const args = input ? `'${input}'` : '';
  try {
    const stdout = execSync(`npx tsx ${SCRIPT_PATH} ${args}`, {
      encoding: 'utf-8',
      timeout: 30000,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    return { stdout: stdout.trim(), exitCode: 0 };
  } catch (error: unknown) {
    const execError = error as { stdout?: string; stderr?: string; status?: number };
    return {
      stdout: (execError.stdout ?? execError.stderr ?? '').trim(),
      exitCode: execError.status ?? 1,
    };
  }
}

describe('auth-navigate.ts', () => {
  it('exits with error when no args provided', () => {
    const result = run();
    expect(result.exitCode).not.toBe(0);
  }, 30000);

  it('exits with error when url is missing', () => {
    const result = run(JSON.stringify({
      loginUrl: 'https://auth.example.com/login',
      credentials: { username: 'user', password: 'pass' },
    }));
    expect(result.exitCode).not.toBe(0);
  }, 30000);

  it('exits with error when loginUrl is missing', () => {
    const result = run(JSON.stringify({
      url: 'https://example.com/dashboard',
      credentials: { username: 'user', password: 'pass' },
    }));
    expect(result.exitCode).not.toBe(0);
  }, 30000);

  it('exits with error when neither credentials nor ssmPath provided', () => {
    const result = run(JSON.stringify({
      url: 'https://example.com/dashboard',
      loginUrl: 'https://auth.example.com/login',
    }));
    expect(result.exitCode).not.toBe(0);
  }, 30000);

  it('exits with error when ssmPath provided without awsProfile', () => {
    const result = run(JSON.stringify({
      url: 'https://example.com/dashboard',
      loginUrl: 'https://auth.example.com/login',
      ssmPath: '/project/dev/credentials',
    }));
    expect(result.exitCode).not.toBe(0);
  }, 30000);

  it('accepts direct credentials as valid input (fails on network, not validation)', () => {
    // This will fail trying to navigate to the login URL (localhost:1 is unreachable)
    // but it should NOT fail on input validation
    const result = run(JSON.stringify({
      url: 'http://localhost:1/dashboard',
      loginUrl: 'http://localhost:1/login',
      credentials: { username: 'testuser', password: 'testpass' },
      timeout: 3000,
    }));

    // Expect failure due to unreachable URL, not input validation
    expect(result.exitCode).not.toBe(0);
    const parsed = JSON.parse(result.stdout);
    expect(parsed.success).toBe(false);
    // The error should be about navigation, not about missing fields
    expect(parsed.error).toBeDefined();
    expect(parsed.error).not.toContain('Required field');
    expect(parsed.error).not.toContain('credentials');
  }, 30000);

  it('accepts ssmPath + awsProfile as valid input (fails on SSM, not validation)', () => {
    // This will fail trying to fetch SSM credentials, but should NOT fail on input validation
    const result = run(JSON.stringify({
      url: 'http://localhost:1/dashboard',
      loginUrl: 'http://localhost:1/login',
      ssmPath: '/nonexistent/path',
      awsProfile: 'nonexistent-profile',
      timeout: 3000,
    }));

    expect(result.exitCode).not.toBe(0);
    const parsed = JSON.parse(result.stdout);
    expect(parsed.success).toBe(false);
    // Should fail on SSM retrieval, not input validation
    expect(parsed.error).toBeDefined();
    expect(parsed.error).not.toContain('Required field');
  }, 30000);
});

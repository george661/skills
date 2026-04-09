#!/usr/bin/env npx tsx
/**
 * Login as a role using credentials, then navigate to a target URL.
 *
 * Supports direct username/password credentials or retrieval from
 * AWS SSM Parameter Store. Login form selectors are configurable.
 *
 * Usage:
 *   npx tsx auth-navigate.ts '{"url": "https://app.example.com", "loginUrl": "https://auth.example.com/login", "credentials": {"username": "user", "password": "pass"}}'
 *   npx tsx auth-navigate.ts '{"url": "https://app.example.com", "loginUrl": "https://auth.example.com/login", "ssmPath": "/project/dev/creds", "awsProfile": "dev-profile"}'
 *
 * Input:
 *   { url: string, loginUrl: string, credentials?: {username, password}, ssmPath?: string, awsProfile?: string,
 *     role?: string, selectors?: {usernameField?, passwordField?, submitButton?, postLoginIndicator?}, timeout?: number }
 *
 * Output:
 *   { success: boolean, url: string, title: string, authenticatedAs: string }
 */

import { getInputArg, parseInput, launchBrowser, closeBrowser, getSsmCredentials, output, fail } from './playwright-client.js';

interface Input {
  url: string;
  loginUrl: string;
  credentials?: { username: string; password: string };
  ssmPath?: string;
  awsProfile?: string;
  role?: string;
  selectors?: {
    usernameField?: string;
    passwordField?: string;
    submitButton?: string;
    postLoginIndicator?: string;
  };
  timeout?: number;
}

const DEFAULT_SELECTORS = {
  usernameField: 'input[name="username"], input[type="email"]',
  passwordField: 'input[name="password"], input[type="password"]',
  submitButton: 'button[type="submit"]',
};

async function main(): Promise<void> {
  let inputArg: string;
  try {
    inputArg = getInputArg();
  } catch {
    fail('Usage: npx tsx auth-navigate.ts \'{"url": "...", "loginUrl": "...", "credentials": {...}}\'');
  }

  const input = parseInput<Input>(inputArg!);

  // Validate required fields
  if (!input.url) {
    fail('Required field: url');
  }
  if (!input.loginUrl) {
    fail('Required field: loginUrl');
  }
  if (!input.credentials && !input.ssmPath) {
    fail('Either credentials or ssmPath must be provided');
  }
  if (input.ssmPath && !input.awsProfile) {
    fail('awsProfile is required when using ssmPath');
  }

  // Resolve credentials
  let credentials: { username: string; password: string };
  if (input.credentials) {
    credentials = input.credentials;
  } else {
    try {
      credentials = getSsmCredentials(input.ssmPath!, input.awsProfile!);
    } catch (error) {
      output({
        success: false,
        url: input.url,
        title: '',
        authenticatedAs: input.role ?? 'unknown',
        error: error instanceof Error ? error.message : String(error),
      });
      process.exit(1);
      return;
    }
  }

  const selectors = {
    usernameField: input.selectors?.usernameField ?? DEFAULT_SELECTORS.usernameField,
    passwordField: input.selectors?.passwordField ?? DEFAULT_SELECTORS.passwordField,
    submitButton: input.selectors?.submitButton ?? DEFAULT_SELECTORS.submitButton,
    postLoginIndicator: input.selectors?.postLoginIndicator,
  };

  const session = await launchBrowser({ timeout: input.timeout });
  try {
    // Navigate to login page
    await session.page.goto(input.loginUrl, { waitUntil: 'networkidle' });

    // Fill username
    const usernameLocator = session.page.locator(selectors.usernameField).first();
    await usernameLocator.fill(credentials.username);

    // Fill password
    const passwordLocator = session.page.locator(selectors.passwordField).first();
    await passwordLocator.fill(credentials.password);

    // Click submit
    const submitLocator = session.page.locator(selectors.submitButton).first();
    await submitLocator.click();

    // Wait for navigation away from login URL or for post-login indicator
    if (selectors.postLoginIndicator) {
      await session.page.locator(selectors.postLoginIndicator).waitFor({
        timeout: input.timeout ?? 30000,
      });
    } else {
      await session.page.waitForURL((url) => url.href !== input.loginUrl, {
        timeout: input.timeout ?? 30000,
      });
    }

    // Navigate to target URL
    await session.page.goto(input.url, { waitUntil: 'networkidle' });

    const title = await session.page.title();

    output({
      success: true,
      url: session.page.url(),
      title,
      authenticatedAs: input.role ?? 'unknown',
    });
  } catch (error) {
    output({
      success: false,
      url: input.url,
      title: '',
      authenticatedAs: input.role ?? 'unknown',
      error: error instanceof Error ? error.message : String(error),
    });
    process.exit(1);
  } finally {
    await closeBrowser(session);
  }
}

main();

import { test as base, expect } from '@playwright/test';

/**
 * Per-test `workflow` fixture. Provides a unique workflow name so drafts
 * don't bleed between tests. The server's autosave bootstrap creates the
 * draft on demand — tests don't need to seed anything first.
 */
type Fixtures = {
  workflow: string;
};

export const test = base.extend<Fixtures>({
  workflow: async ({}, use, testInfo) => {
    const name = `e2e-${testInfo.title.replace(/\W+/g, '-').toLowerCase()}`;
    await use(name);
  },
});

/**
 * Modifier key for chord shortcuts, matching what useBuilderKeyboard's
 * platform check will see in the browser: metaKey on macOS, ctrlKey elsewhere.
 * The browser runs on the same host as the runner, so process.platform is
 * an authoritative proxy that avoids the deprecated navigator.platform.
 */
export const MOD_KEY = process.platform === 'darwin' ? 'Meta' : 'Control';

export { expect };

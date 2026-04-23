import { test, expect } from '@playwright/test';
import { gotoRoute } from './helpers';

// The dashboard has several routes that fetch data from endpoints which may not
// be configured in the test environment (checkpoints, SSE). We don't gate on
// console-error-free because those 404s are legitimate empty-state signals.
// Each spec asserts the heading renders and the page reaches a stable state.

test.describe('dashboard route (/)', () => {
  test('renders header and sidebar nav links', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'DAG Dashboard' })).toBeVisible();
    await expect(page.locator('#sidebar a[data-route="/"]')).toBeVisible();
    await expect(page.locator('#sidebar a[data-route="/workflows"]')).toBeVisible();
    await expect(page.locator('#sidebar a[data-route="/history"]')).toBeVisible();
    await expect(page.locator('#sidebar a[data-route="/checkpoints"]')).toBeVisible();
    await expect(page.locator('#sidebar a[data-route="/settings"]')).toBeVisible();
  });

  test('sidebar navigation routes work', async ({ page }) => {
    await page.goto('/');
    await page.locator('#sidebar a[data-route="/history"]').click();
    await expect(page).toHaveURL(/#\/history$/);
    // Router toggles the `active` class on the matching link after hashchange.
    await expect(page.locator('#sidebar a[data-route="/history"]')).toHaveClass(/active/);

    await page.locator('#sidebar a[data-route="/workflows"]').click();
    await expect(page).toHaveURL(/#\/workflows$/);
    await expect(page.locator('#sidebar a[data-route="/workflows"]')).toHaveClass(/active/);
  });
});

test.describe('history route (/history)', () => {
  test('renders Workflow History heading', async ({ page }) => {
    await gotoRoute(page, '#/history');
    await expect(
      page.getByRole('heading', { name: /Workflow History/i }),
    ).toBeVisible();
  });
});

test.describe('workflows route (/workflows)', () => {
  test('renders Workflows heading', async ({ page }) => {
    await gotoRoute(page, '#/workflows');
    await expect(
      page.getByRole('heading', { name: 'Workflows', exact: true }),
    ).toBeVisible();
  });
});

test.describe('checkpoints route (/checkpoints)', () => {
  test('renders Checkpoint Workflows heading', async ({ page }) => {
    await gotoRoute(page, '#/checkpoints');
    await expect(
      page.getByRole('heading', { name: /Checkpoint Workflows/i }),
    ).toBeVisible();
  });

  test('shows empty-state when checkpoint_prefix is not configured', async ({ page }) => {
    await gotoRoute(page, '#/checkpoints');
    await expect(page.locator('.empty-state-text')).toContainText(
      /not configured/i,
    );
  });
});

test.describe('settings route (/settings)', () => {
  test('renders Settings heading', async ({ page }) => {
    await gotoRoute(page, '#/settings');
    await expect(
      page.locator('.settings-title', { hasText: 'Settings' }).first(),
    ).toBeVisible();
  });
});

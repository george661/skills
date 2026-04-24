import type { Page } from '@playwright/test';

/**
 * Navigate to a hash route and wait for the SPA router to render.
 * The app re-renders #route-container on hashchange; we wait for network idle
 * as a proxy for "route ready".
 */
export async function gotoRoute(page: Page, hash: string): Promise<void> {
  if (!page.url().startsWith('http')) {
    await page.goto('/');
  }
  await page.evaluate((h) => {
    window.location.hash = h;
  }, hash);
  await page.waitForLoadState('networkidle');
}

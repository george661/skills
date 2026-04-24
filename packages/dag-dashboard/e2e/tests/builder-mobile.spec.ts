import { test, expect, devices, type Page, type ConsoleMessage } from '@playwright/test';

/**
 * Fail the block if any console error fires. Inlined because the shared
 * helpers module doesn't export this (yet).
 *
 * Filters browser-native resource-load errors whose source URL points at
 * endpoints that are legitimately-404 in a fresh-workflow state (no draft
 * saved yet, no gates pending, no checkpoints). The browser emits
 * "Failed to load resource: ... 404" with the URL in msg.location().url —
 * the msg text itself doesn't include the URL, so we have to inspect
 * location to decide whether to ignore.
 */
const EXPECTED_404_URL_PATTERNS = [
  /\/api\/workflows\/[^/]+\/drafts\/current/,
  /\/api\/checkpoints\/workflows/,
];

function isExpectedResourceError(msg: ConsoleMessage): boolean {
  const text = msg.text();
  if (!/Failed to load resource/i.test(text)) return false;
  const url = msg.location()?.url ?? '';
  return EXPECTED_404_URL_PATTERNS.some((re) => re.test(url));
}

async function expectNoConsoleErrors(
  page: Page,
  run: () => Promise<void>,
): Promise<void> {
  const errors: string[] = [];
  const listener = (msg: ConsoleMessage): void => {
    if (msg.type() !== 'error') return;
    if (isExpectedResourceError(msg)) return;
    errors.push(msg.text());
  };
  page.on('console', listener);
  try {
    await run();
  } finally {
    page.off('console', listener);
  }
  if (errors.length > 0) {
    throw new Error(`Console errors:\n  - ${errors.join('\n  - ')}`);
  }
}

/**
 * GW-5253: Mobile + touch-gesture coverage for the /builder route.
 *
 * Three viewport groups:
 *   - Desktop (1024×768) — regression guard
 *   - iPad portrait (768×1024) — readable layout, pinch/pan work
 *   - iPhone SE (320×568) — critical paths (view + validate + publish) usable
 *
 * Pinch/pan can't be truly tested with Playwright (multi-touch isn't
 * exposed), but the React Flow pinch-zoom handler is wired to the
 * ``wheel`` + ``ctrlKey`` event (browser pinch synthesises this). We
 * dispatch that event and assert the transform changes.
 */

async function openBuilder(page: Page, workflow = 'sample'): Promise<void> {
  await page.goto(`/?workflow=${encodeURIComponent(workflow)}#/builder`);
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeVisible();
  await expect(page.locator('.react-flow')).toBeVisible({ timeout: 10_000 });
}

test.describe('builder at desktop (regression)', () => {
  test.use({ viewport: { width: 1024, height: 768 } });

  test('Split view still works on desktop', async ({ page }) => {
    await expectNoConsoleErrors(page, async () => {
      await openBuilder(page);
      await page.getByRole('button', { name: 'Split', exact: true }).click();
      await expect(page.locator('.yaml-code-view, pre').first()).toBeVisible();
    });
  });
});

const iPadMini = devices['iPad Mini'];
test.describe('builder at iPad portrait (768×1024)', () => {
  test.use({
    viewport: { width: 768, height: 1024 },
    userAgent: iPadMini.userAgent,
    deviceScaleFactor: iPadMini.deviceScaleFactor,
    isMobile: iPadMini.isMobile,
    hasTouch: iPadMini.hasTouch,
  });

  test('toolbar, canvas, and action buttons are visible without horizontal scroll', async ({
    page,
  }) => {
    await expectNoConsoleErrors(page, async () => {
      await openBuilder(page);

      // Action buttons must be reachable without horizontal scroll.
      for (const name of ['Save', 'Publish', 'Validate']) {
        await expect(page.getByRole('button', { name, exact: true })).toBeVisible();
      }

      // Horizontal scroll is the classic mobile failure mode — assert body width <= viewport.
      const bodyScrollWidth = await page.evaluate(() => document.body.scrollWidth);
      const viewportWidth = await page.evaluate(() => window.innerWidth);
      expect(bodyScrollWidth).toBeLessThanOrEqual(viewportWidth + 1);
    });
  });

  // Regression test for GW-5337: Playwright pinch-zoom E2E test skipped - WheelEvent does not reach React Flow D3 handler
  // This test asserts correct behavior (pinch-zoom should change transform) but FAILS because:
  // - page.mouse.wheel() lacks ctrlKey support
  // - WheelEvent dispatched on .react-flow doesn't reach D3 handler on .react-flow__pane
  // Expected to pass once GW-5337 is resolved.
  test('pinch-zoom (wheel+ctrlKey) changes canvas transform', async ({ page }) => {
    await openBuilder(page);

    // React Flow keeps .react-flow__viewport at visibility:hidden until the
    // initial transform is applied. Assert the parent .react-flow is visible
    // and poll for viewport's transform to be set before driving interaction.
    await expect(page.locator('.react-flow')).toBeVisible();
    const viewport = page.locator('.react-flow__viewport');
    await expect
      .poll(async () => viewport.evaluate((el) => (el as HTMLElement).style.transform))
      .not.toEqual('');

    const before = await viewport.evaluate((el) => (el as HTMLElement).style.transform);

    // React Flow's pinch-zoom listens to wheel events with ctrlKey=true,
    // which is how browsers synthesise pinch gestures on touch surfaces.
    // Playwright's page.mouse.wheel() does not support ctrlKey, so dispatch
    // the WheelEvent directly on the canvas element.
    const canvas = page.locator('.react-flow').first();
    const box = await canvas.boundingBox();
    if (!box) throw new Error('canvas has no bounding box');
    await canvas.evaluate((el, pos) => {
      const rect = el.getBoundingClientRect();
      const event = new WheelEvent('wheel', {
        bubbles: true,
        cancelable: true,
        clientX: rect.left + pos.x,
        clientY: rect.top + pos.y,
        deltaY: -200,
        ctrlKey: true,
      });
      el.dispatchEvent(event);
    }, { x: box.width / 2, y: box.height / 2 });

    await expect
      .poll(async () => viewport.evaluate((el) => (el as HTMLElement).style.transform))
      .not.toEqual(before);
  });
});

const iPhoneSE = devices['iPhone SE'];
test.describe('builder at iPhone SE (320×568)', () => {
  test.use({
    viewport: { width: 320, height: 568 },
    userAgent: iPhoneSE.userAgent,
    deviceScaleFactor: iPhoneSE.deviceScaleFactor,
    isMobile: iPhoneSE.isMobile,
    hasTouch: iPhoneSE.hasTouch,
  });

  test('loads without horizontal scroll and shows canvas', async ({ page }) => {
    await expectNoConsoleErrors(page, async () => {
      await openBuilder(page);

      await expect(page.locator('.react-flow')).toBeVisible();

      const bodyScrollWidth = await page.evaluate(() => document.body.scrollWidth);
      expect(bodyScrollWidth).toBeLessThanOrEqual(321);
    });
  });

  test('Validate button is tappable and fires /api/workflows/validate', async ({ page }) => {
    await openBuilder(page);

    const validatePromise = page.waitForRequest(
      (req) => req.url().includes('/api/workflows/validate') && req.method() === 'POST',
      { timeout: 5_000 },
    );
    await page.getByRole('button', { name: 'Validate', exact: true }).tap();
    const validateReq = await validatePromise;
    expect(validateReq).toBeTruthy();
  });

  test('critical action buttons meet 44×44 touch target minimum', async ({ page }) => {
    await openBuilder(page);

    for (const name of ['Save', 'Validate']) {
      const btn = page.getByRole('button', { name, exact: true });
      const box = await btn.boundingBox();
      if (!box) throw new Error(`no bounding box for ${name}`);
      // WCAG 2.5.5 / Apple HIG minimum tappable target is 44×44.
      expect(box.width).toBeGreaterThanOrEqual(44);
      expect(box.height).toBeGreaterThanOrEqual(44);
    }
  });
});

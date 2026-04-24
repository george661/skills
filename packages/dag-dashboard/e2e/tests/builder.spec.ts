import { test, expect, MOD_KEY } from './fixtures';
import type { Page } from '@playwright/test';

// The React canvas mounts into the SPA's #route-container when /builder is hit.
// These tests need the builder feature flag on — start-server.sh sets it.

async function openBuilder(page: Page, workflow: string): Promise<void> {
  await page.goto(`/?workflow=${encodeURIComponent(workflow)}#/builder`);
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeVisible();
  // Canvas is gated behind the autosave bootstrap — allow extra time.
  await expect(page.locator('.react-flow')).toBeVisible({ timeout: 10_000 });
}

/**
 * Drop a node on the canvas using the `application/x-dag-node-type`
 * dataTransfer channel the hook accepts. Simulating HTML5 drag-and-drop
 * directly because Playwright's dragTo doesn't set custom dataTransfer types.
 */
async function dropNodeOnCanvas(page: Page, nodeType: string): Promise<void> {
  const canvas = page.locator('.workflow-canvas');
  await canvas.waitFor({ state: 'visible' });
  const box = await canvas.boundingBox();
  if (!box) throw new Error('canvas has no bounding box');

  await page.evaluate(
    ({ x, y, type }) => {
      const target = document.querySelector('.workflow-canvas') as HTMLElement | null;
      if (!target) throw new Error('no .workflow-canvas in DOM');
      const dt = new DataTransfer();
      dt.setData('application/x-dag-node-type', type);
      const init = {
        bubbles: true,
        cancelable: true,
        clientX: x,
        clientY: y,
        dataTransfer: dt,
      };
      target.dispatchEvent(new DragEvent('dragover', init));
      target.dispatchEvent(new DragEvent('drop', init));
    },
    { x: box.x + box.width / 2, y: box.y + box.height / 2, type: nodeType },
  );
}

const canvasNodeCount = (page: Page) => page.locator('.react-flow__node').count();

test.describe('builder route (/builder)', () => {
  test('renders toolbar, canvas, and view-mode toggles', async ({ page, workflow }) => {
    await openBuilder(page, workflow);
    for (const name of ['Save', 'Publish', 'Run', 'Validate', 'Hidden', 'Split', 'Full']) {
      await expect(page.getByRole('button', { name, exact: true })).toBeVisible();
    }
  });

  test('drop adds a node to the canvas', async ({ page, workflow }) => {
    await openBuilder(page, workflow);
    expect(await canvasNodeCount(page)).toBe(0);
    await dropNodeOnCanvas(page, 'bash');
    await expect.poll(() => canvasNodeCount(page)).toBe(1);
  });

  test('Cmd+Z undoes a drop; Cmd+Shift+Z redoes it', async ({ page, workflow }) => {
    await openBuilder(page, workflow);
    await dropNodeOnCanvas(page, 'bash');
    await expect.poll(() => canvasNodeCount(page)).toBe(1);

    // Focus the canvas so keydown reaches the document-level handler.
    await page.locator('.workflow-canvas').click({ position: { x: 10, y: 10 } });

    await page.keyboard.press(`${MOD_KEY}+KeyZ`);
    await expect.poll(() => canvasNodeCount(page)).toBe(0);

    await page.keyboard.press(`${MOD_KEY}+Shift+KeyZ`);
    await expect.poll(() => canvasNodeCount(page)).toBe(1);
  });

  test('Cmd+S inside Name input does not trap the user', async ({ page, workflow }) => {
    await openBuilder(page, workflow);

    const nameInput = page.locator('.builder-toolbar input[type="text"]').first();
    await nameInput.click();
    await nameInput.fill('sample-workflow');

    await page.keyboard.press(`${MOD_KEY}+KeyS`);

    // The input guard in useBuilderKeyboard must suppress Cmd+S when focus is
    // inside a text input. If it didn't, the save handler (or the browser's
    // native save dialog) would steal focus and the input value would likely
    // be lost or the input would lose focus. Verify the input is still focused
    // and still holds the typed value.
    await expect(nameInput).toHaveValue('sample-workflow');
    await expect(nameInput).toBeFocused();

    // And the user can keep typing into the same input.
    await page.keyboard.type('-v2');
    await expect(nameInput).toHaveValue('sample-workflow-v2');
  });

  test('view-mode Split shows YAML pane; Hidden hides it', async ({ page, workflow }) => {
    await openBuilder(page, workflow);
    await page.getByRole('button', { name: 'Split', exact: true }).click();

    const yamlPane = page.locator('.yaml-code-view, pre').first();
    await expect(yamlPane).toBeVisible();

    await page.getByRole('button', { name: 'Hidden', exact: true }).click();
    await expect(yamlPane).toBeHidden();
  });

  test('dropping a node flips autosave to unsaved', async ({ page, workflow }) => {
    await openBuilder(page, workflow);
    // The autosave hook only tracks graph changes (markDirty called from
    // onGraphChange), not toolbar-input edits. Drop a node to dirty the canvas.
    await dropNodeOnCanvas(page, 'bash');
    await expect(page.getByTestId('unsaved-indicator')).toBeVisible();
  });
});

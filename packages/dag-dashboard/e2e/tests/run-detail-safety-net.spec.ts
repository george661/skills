/**
 * E2E — GW-5423: SSE+REST safety net, virtualized logs, chat lock.
 *
 * Opt-in suite (PLAYWRIGHT_E2E=1). These tests exercise runtime behavior of
 * the modules introduced in GW-5423; they don't need a seeded run because the
 * assertions run against classes exposed on `window` plus direct DOM
 * manipulation. The "full terminal-state within 6s" measurement from AC-6
 * lives in the broader mobile/e2e suite where multi-run seeding is available.
 */
import { test, expect } from '@playwright/test';

test.describe('GW-5423 safety-net modules', () => {
    test('VirtualizedLogList windows rendering above threshold', async ({ page }) => {
        await page.goto('/');

        const result = await page.evaluate(() => {
            const V = (window as any).VirtualizedLogList;
            if (typeof V !== 'function') return { error: 'VirtualizedLogList missing' };

            const host = document.createElement('div');
            host.style.height = '400px';
            host.style.overflow = 'auto';
            document.body.appendChild(host);

            const list = new V({
                container: host,
                rowHeight: 18,
                threshold: 200,
                renderRow: (row: any) => `<div class="row">${row}</div>`,
            });
            const rows: number[] = [];
            for (let i = 0; i < 1000; i += 1) rows.push(i);
            list.setRows(rows);

            // Above threshold, DOM row count should be far below total.
            const domRowCount = host.querySelectorAll('.row').length;
            const totalRowCount = rows.length;

            list.destroy();
            host.remove();
            return { domRowCount, totalRowCount };
        });

        expect(result.error).toBeUndefined();
        expect(result.totalRowCount).toBe(1000);
        expect(result.domRowCount).toBeLessThan(400);
        expect(result.domRowCount).toBeGreaterThan(0);
    });

    test('VirtualizedLogList renders naively below threshold', async ({ page }) => {
        await page.goto('/');

        const result = await page.evaluate(() => {
            const V = (window as any).VirtualizedLogList;
            const host = document.createElement('div');
            host.style.height = '400px';
            host.style.overflow = 'auto';
            document.body.appendChild(host);

            const list = new V({
                container: host,
                rowHeight: 18,
                threshold: 200,
                renderRow: (row: any) => `<div class="row">${row}</div>`,
            });
            const rows = Array.from({ length: 50 }, (_, i) => i);
            list.setRows(rows);

            const domRowCount = host.querySelectorAll('.row').length;
            list.destroy();
            host.remove();
            return { domRowCount };
        });

        expect(result.domRowCount).toBe(50);
    });

    test('ChatPanel locks input when a prompt node is running', async ({ page }) => {
        await page.goto('/');

        const result = await page.evaluate(() => {
            const host = document.createElement('div');
            host.id = 'test-chat-host';
            document.body.appendChild(host);

            const CP = (window as any).ChatPanel;
            const panel = new CP('test-chat-host', {
                mode: 'run',
                runId: 'test-run',
                nodes: [
                    { id: 'n1', node_name: 'n1', node_data: { type: 'prompt' }, status: 'pending' },
                    { id: 'n2', node_name: 'n2', node_data: { type: 'bash' }, status: 'pending' },
                ],
            });
            panel.render();

            // Fire a node_started for the prompt node.
            panel.handleWorkflowEvent({
                event_type: 'node_started',
                node_id: 'n1',
                metadata: {},
            });

            const textarea = host.querySelector('.chat-input') as HTMLTextAreaElement | null;
            const lockedClass = host.querySelector('.chat-input-form--locked') !== null;
            const indicatorText = host.querySelector('.chat-input-lock-indicator')?.textContent || '';
            const disabled = textarea ? textarea.disabled : null;

            // Cleanup for subsequent tests.
            panel.destroy();
            host.remove();

            return { lockedClass, indicatorText, disabled };
        });

        expect(result.lockedClass).toBe(true);
        expect(result.disabled).toBe(true);
        expect(result.indicatorText).toContain('Agent is thinking');
    });

    test('ChatPanel ignores node_started for non-prompt node types', async ({ page }) => {
        await page.goto('/');

        const result = await page.evaluate(() => {
            const host = document.createElement('div');
            host.id = 'test-chat-host-2';
            document.body.appendChild(host);

            const CP = (window as any).ChatPanel;
            const panel = new CP('test-chat-host-2', {
                mode: 'run',
                runId: 'test-run',
                nodes: [
                    { id: 'n1', node_name: 'n1', node_data: { type: 'bash' }, status: 'pending' },
                ],
            });
            panel.render();

            panel.handleWorkflowEvent({
                event_type: 'node_started',
                node_id: 'n1',
                metadata: {},
            });

            const disabled = (host.querySelector('.chat-input') as HTMLTextAreaElement | null)?.disabled;
            panel.destroy();
            host.remove();
            return { disabled };
        });

        expect(result.disabled).toBe(false);
    });

    test('ChatPanel unlocks on workflow terminal even if node_completed was dropped', async ({ page }) => {
        await page.goto('/');

        const result = await page.evaluate(async () => {
            const host = document.createElement('div');
            host.id = 'test-chat-host-3';
            document.body.appendChild(host);

            const CP = (window as any).ChatPanel;
            const panel = new CP('test-chat-host-3', {
                mode: 'run',
                runId: 'test-run',
                nodes: [
                    { id: 'n1', node_name: 'n1', node_data: { type: 'prompt' }, status: 'pending' },
                ],
            });
            panel.render();

            // Start a prompt node → locked
            panel.handleWorkflowEvent({ event_type: 'node_started', node_id: 'n1', metadata: {} });
            const lockedDuring = (host.querySelector('.chat-input') as HTMLTextAreaElement).disabled;

            // Simulate a dropped node_completed by jumping straight to workflow_completed.
            panel.handleWorkflowEvent({ event_type: 'workflow_completed', node_id: null, metadata: {} });

            // Unlock is debounced 100ms — wait for the timer.
            await new Promise((r) => setTimeout(r, 200));

            const lockedAfter = (host.querySelector('.chat-input') as HTMLTextAreaElement).disabled;
            panel.destroy();
            host.remove();
            return { lockedDuring, lockedAfter };
        });

        expect(result.lockedDuring).toBe(true);
        expect(result.lockedAfter).toBe(false);
    });
});

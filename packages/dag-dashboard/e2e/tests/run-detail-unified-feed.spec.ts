/**
 * E2E — unified feed layout (GW-5422).
 *
 * Opt-in suite (PLAYWRIGHT_E2E=1). Navigates to the dashboard index and
 * asserts that all unified-feed modules are loaded and available on the
 * window. The full run-detail flow (trigger workflow → see progress cards)
 * needs seeded run data and lives in the larger mobile/e2e suites.
 */
import { test, expect } from '@playwright/test';

test.describe('Unified feed modules load', () => {
    test('every GW-5422 module is available on window', async ({ page }) => {
        await page.goto('/');

        const exposed = await page.evaluate(() => ({
            hasChatPanel: typeof (window as any).ChatPanel === 'function',
            hasWorkflowProgressCard: typeof (window as any).WorkflowProgressCard === 'function',
            hasEventToMessages: typeof (window as any).EventToMessages === 'object',
            hasNodeScrollBus: typeof (window as any).NodeScrollBus === 'object',
            hasStateSlideover: typeof (window as any).StateSlideover === 'object',
            hasResizableSplit: typeof (window as any).ResizableSplit === 'function',
            // TracePanel is sunset — must NOT be available any longer.
            noTracePanel: typeof (window as any).TracePanel === 'undefined',
        }));

        expect(exposed.hasChatPanel).toBeTruthy();
        expect(exposed.hasWorkflowProgressCard).toBeTruthy();
        expect(exposed.hasEventToMessages).toBeTruthy();
        expect(exposed.hasNodeScrollBus).toBeTruthy();
        expect(exposed.hasStateSlideover).toBeTruthy();
        expect(exposed.hasResizableSplit).toBeTruthy();
        expect(exposed.noTracePanel).toBeTruthy();
    });

    test('event-to-messages folds channel_updated into owning card', async ({ page }) => {
        await page.goto('/');

        const result = await page.evaluate(() => {
            const ETM = (window as any).EventToMessages;
            const state = ETM.createState();
            const events = [
                { event_type: 'node_started', node_id: 'n1', metadata: {} },
                { event_type: 'channel_updated', node_id: 'n1',
                  metadata: { writer_node_id: 'n1', channel_key: 'seed', value: 'v1' } },
            ];
            const out: any[] = [];
            for (const ev of events) {
                for (const m of ETM.eventToMessages(ev, state)) {
                    out.push({ type: m.type, subtype: m.subtype, nodeId: m.nodeId });
                }
            }
            return out;
        });

        expect(result).toEqual([
            { type: 'progress_card', subtype: 'node_started', nodeId: 'n1' },
            { type: 'progress_card', subtype: 'channel_updated', nodeId: 'n1' },
        ]);
    });

    test('NodeScrollBus broadcasts to subscribers with source tag', async ({ page }) => {
        await page.goto('/');

        const received = await page.evaluate(() => {
            const bus = (window as any).NodeScrollBus;
            bus.clear();
            const calls: any[] = [];
            bus.subscribe((nodeId: string, source: string) => calls.push({ nodeId, source }));
            bus.trigger('n1', 'dag');
            bus.trigger('n2', 'feed');
            bus.clear();
            bus.trigger('n3', 'dag'); // should not be received after clear
            return calls;
        });

        expect(received).toEqual([
            { nodeId: 'n1', source: 'dag' },
            { nodeId: 'n2', source: 'feed' },
        ]);
    });
});

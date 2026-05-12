/**
 * End-to-end trigger flow: seed a workflow YAML into the harness workflows
 * dir, open the trigger form in the browser, submit it, wait for the run to
 * reach a terminal state, and assert UI + API agree.
 *
 * Exercises every link the GW-5770/GW-5774 fixes depended on:
 *   - /api/definitions lists the seeded workflow (reload_from_db → app.state)
 *   - /api/trigger is mounted and responds (always-mount + runtime gate)
 *   - trigger form renders without console errors (pattern= → data-pattern)
 *   - form POST → run id → run-detail page → SSE events → completion
 */
import { promises as fs } from 'fs';
import * as path from 'path';

import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

import { gotoRoute } from './helpers';

const WORKFLOW_NAME = 'e2e-trigger-smoke';

// A trivial bash-only workflow the harness can run with zero external deps.
// The pattern on `greeting` is deliberately `[a-zA-Z0-9_-]+` so this spec
// also exercises the GW-5774 fix (raw pattern= crashes under Chromium's
// ECMAScript `v` flag).
const WORKFLOW_YAML = `
name: ${WORKFLOW_NAME}
config:
  checkpoint_prefix: ${WORKFLOW_NAME}
inputs:
  greeting:
    type: string
    required: true
    pattern: "^[a-zA-Z0-9_-]+$"
nodes:
  - id: say_hello
    name: Say hello
    type: bash
    script: |
      echo "hello $greeting"
`.trimStart();

async function fetchJson(page: Page, url: string): Promise<any> {
    const res = await page.request.get(url);
    expect(res.ok(), `${url} → ${res.status()} ${res.statusText()}`).toBeTruthy();
    return res.json();
}

async function resolveWorkflowsDir(page: Page): Promise<string> {
    const data = await fetchJson(page, '/api/settings');
    const entry = data?.settings?.workflows_dir;
    expect(entry?.value, '/api/settings must expose workflows_dir').toBeTruthy();
    return String(entry.value);
}

async function enableTrigger(page: Page): Promise<void> {
    const res = await page.request.put('/api/settings', {
        data: { updates: { trigger_enabled: true } },
    });
    expect(res.ok(), `enable trigger → ${res.status()}`).toBeTruthy();
}

async function pollRunStatus(
    page: Page,
    runId: string,
    terminalStatuses = ['completed', 'failed', 'cancelled', 'paused'],
    timeoutMs = 30_000,
): Promise<any> {
    const deadline = Date.now() + timeoutMs;
    let last: any = null;
    // GET /api/workflows/{run_id} returns { run: {...}, nodes: [...], totals: {...} }.
    // The status lives under `run.status`.
    while (Date.now() < deadline) {
        const res = await page.request.get(`/api/workflows/${runId}`);
        if (res.ok()) {
            last = await res.json();
            const status = last?.run?.status;
            if (status && terminalStatuses.includes(status)) return last;
        }
        await page.waitForTimeout(250);
    }
    throw new Error(
        `Run ${runId} did not reach terminal status within ${timeoutMs}ms. ` +
            `Last known status: ${last?.run?.status ?? 'unknown'}. ` +
            `Last body keys: ${last ? Object.keys(last).join(',') : 'none'}.`,
    );
}

test.describe('workflow trigger + orchestration (end-to-end)', () => {
    test.setTimeout(60_000);

    test('seed → list → trigger → run completes', async ({ page }) => {
        // 1. Capture any browser console error so we don't miss the
        //    GW-5774 pattern= regression sneaking back in.
        const consoleErrors: string[] = [];
        page.on('pageerror', (err) => {
            consoleErrors.push(err.message);
        });
        page.on('console', (msg) => {
            if (msg.type() === 'error') consoleErrors.push(msg.text());
        });

        // 2. Seed a workflow YAML into the harness's workflows_dir.
        //    Use the live /api/settings value — the harness creates a fresh
        //    mktemp dir per session, so hard-coding would be wrong.
        await page.goto('/');
        await enableTrigger(page);
        const workflowsDir = await resolveWorkflowsDir(page);
        const yamlPath = path.join(workflowsDir, `${WORKFLOW_NAME}.yaml`);
        await fs.mkdir(workflowsDir, { recursive: true });
        await fs.writeFile(yamlPath, WORKFLOW_YAML, 'utf8');

        try {
            // 3. Definitions endpoint should see the new file.
            const defs = await fetchJson(page, '/api/definitions');
            const names = (defs || []).map((d: any) => d?.name);
            expect(names).toContain(WORKFLOW_NAME);

            // 4. Navigate to the trigger form and render the inputs.
            await gotoRoute(page, `#/workflow-trigger/${WORKFLOW_NAME}`);
            await expect(
                page.getByRole('heading', { name: `Run Workflow: ${WORKFLOW_NAME}` }),
            ).toBeVisible();

            // 5. The GW-5774 fix: the input must use data-pattern, never
            //    the HTML `pattern=` attribute (that breaks Chromium).
            const greeting = page.locator('#input-greeting');
            await expect(greeting).toBeVisible();
            await expect(greeting).toHaveAttribute('data-pattern', '^[a-zA-Z0-9_-]+$');
            await expect(greeting).not.toHaveAttribute('pattern', /.+/);

            // No browser-side pattern compilation errors by this point.
            expect(
                consoleErrors.filter((e) =>
                    e.includes('Invalid regular expression') ||
                    e.includes('Invalid character in character class'),
                ),
                `browser console should be free of pattern= regex errors: ${JSON.stringify(consoleErrors)}`,
            ).toHaveLength(0);

            // 6. Fill the form and submit. The UI redirects to #/workflow/<runId>.
            await greeting.fill('world');
            const triggerRequest = page.waitForResponse((r) =>
                r.url().includes('/api/trigger') && r.request().method() === 'POST',
            );
            await page.locator('#trigger-workflow-form button[type="submit"], #trigger-workflow-form [type="submit"]').first().click();
            const triggerResponse = await triggerRequest;
            expect(
                triggerResponse.status(),
                `POST /api/trigger → ${triggerResponse.status()}`,
            ).toBe(200);
            const triggerBody = await triggerResponse.json();
            expect(triggerBody.run_id, 'trigger response must include run_id').toBeTruthy();
            expect(triggerBody.conversation_id, 'trigger response must include conversation_id').toBeTruthy();

            const runId = triggerBody.run_id as string;

            // 7. UI should navigate to the run-detail page.
            await expect(page).toHaveURL(new RegExp(`#/workflow/${runId}$`));

            // 8. Backend should process the run to completion.
            //    dag-executor fires on trigger and runs the 1-node bash DAG.
            //    Success means the run row reaches status=completed and the
            //    single bash node executed successfully.
            const terminal = await pollRunStatus(page, runId);
            expect(
                terminal?.run?.status,
                `run ${runId} expected to complete; body=${JSON.stringify(terminal)}`,
            ).toBe('completed');

            // DB stores the YAML node's `id:` in the node_name column (the
            // name column in YAML is an optional display label). Match on
            // node_name to be robust against future schema renames.
            const bashNode = (terminal?.nodes || []).find(
                (n: any) => n?.node_name === 'say_hello',
            );
            expect(bashNode, 'say_hello node should have executed').toBeTruthy();
            expect(bashNode?.status, 'say_hello node must have completed').toBe('completed');
        } finally {
            // Cleanup: remove the seeded YAML so other specs aren't polluted.
            await fs.rm(yamlPath, { force: true });
        }
    });
});

/**
 * E2E — Pending workspace changes UI (GW-5937).
 *
 * Drives a real workflow trigger to seed a workspace with .workflow/workflow.yaml,
 * mutates the seeded YAML post-run to create a pending change, and exercises
 * the GET / POST routes plus the run-detail UI section.
 *
 * Trigger flow is the only path that produces a real workspace channel value
 * in the DB; no admin endpoint exists to seed runs directly.
 */
import { promises as fs } from 'fs';
import * as path from 'path';

import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

import { gotoRoute } from './helpers';

const WORKFLOW_NAME = 'e2e-pending-changes';

// Trivial single-bash-node workflow — same shape as workflow-trigger-e2e but
// without inputs so /api/trigger inputs={} doesn't fail validation.
const WORKFLOW_YAML = `
name: ${WORKFLOW_NAME}
config:
  checkpoint_prefix: ${WORKFLOW_NAME}
nodes:
  - id: noop
    name: No-op
    type: bash
    script: |
      echo "hello"
`.trimStart();

async function fetchJson(page: Page, url: string): Promise<any> {
    const res = await page.request.get(url);
    expect(res.ok(), `${url} -> ${res.status()}`).toBeTruthy();
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
    expect(res.ok(), `enable trigger -> ${res.status()}`).toBeTruthy();
}

async function pollRunStatus(page: Page, runId: string, timeoutMs = 60_000): Promise<any> {
    const deadline = Date.now() + timeoutMs;
    const terminal = new Set(['completed', 'failed', 'cancelled', 'paused']);
    let last: any = null;
    while (Date.now() < deadline) {
        const res = await page.request.get(`/api/workflows/${runId}`);
        if (res.ok()) {
            last = await res.json();
            const s = last?.run?.status;
            if (s && terminal.has(s)) return last;
        }
        await page.waitForTimeout(250);
    }
    throw new Error(
        `Run ${runId} did not reach terminal status in ${timeoutMs}ms; last=${JSON.stringify(last?.run ?? {})}`,
    );
}

interface SeededRun {
    runId: string;
    workspacePath: string;
    workflowYamlPath: string;
}

async function seedAndTriggerRun(page: Page, workflowsDir: string): Promise<SeededRun> {
    await enableTrigger(page);

    const yamlPath = path.join(workflowsDir, `${WORKFLOW_NAME}.yaml`);
    await fs.mkdir(workflowsDir, { recursive: true });
    await fs.writeFile(yamlPath, WORKFLOW_YAML, 'utf8');

    // /api/trigger TriggerRequest model: { workflow, inputs?, source, ... }
    // Note `workflow` (not workflow_name) and `source` is required.
    const triggerResp = await page.request.post('/api/trigger', {
        data: {
            workflow: WORKFLOW_NAME,
            inputs: {},
            source: 'pending-changes-e2e',
        },
    });
    expect(triggerResp.ok(), `POST /api/trigger -> ${triggerResp.status()} ${await triggerResp.text()}`).toBeTruthy();
    const triggerBody = await triggerResp.json();
    const runId = triggerBody.run_id as string;
    expect(runId).toBeTruthy();

    await pollRunStatus(page, runId);

    // Read the workspace channel to discover the workspace path.
    // /api/workflows/{run_id}/channels returns objects keyed `channel_key` (not `key`)
    // with `value` already JSON-deserialized (string or {"value": ...} dict).
    const channels = await fetchJson(page, `/api/workflows/${runId}/channels`);
    const wsChannel = (channels?.channels ?? []).find(
        (c: any) => c.channel_key === 'workspace',
    );
    expect(
        wsChannel,
        `workspace channel must exist after run; got=${JSON.stringify(channels)}`,
    ).toBeTruthy();
    const rawVal = wsChannel.value;
    const workspacePath = typeof rawVal === 'string' ? rawVal : rawVal?.value;
    expect(workspacePath, 'workspace path must be a string').toBeTruthy();

    return { runId, workspacePath, workflowYamlPath: yamlPath };
}

async function cleanupSeed(yamlPath: string): Promise<void> {
    await fs.rm(yamlPath, { force: true });
}

test.describe('Pending workspace changes (GW-5937)', () => {
    test.setTimeout(120_000);

    test('section is hidden when workspace has no pending changes', async ({ page }) => {
        const workflowsDir = await resolveWorkflowsDir(page);
        const seed = await seedAndTriggerRun(page, workflowsDir);
        try {
            const pending = await fetchJson(page, `/api/runs/${seed.runId}/pending-changes`);
            expect(pending.changes, 'no mutations -> empty changes').toEqual([]);

            await page.goto('/');
            await gotoRoute(page, `#/workflow/${seed.runId}`);
            const section = page.locator('#pending-workspace-changes');
            await expect(section).toBeAttached();
            await expect(section).toHaveAttribute('hidden', '');
        } finally {
            await cleanupSeed(seed.workflowYamlPath);
        }
    });

    test('section becomes visible with diff when the seeded YAML is mutated', async ({ page }) => {
        const workflowsDir = await resolveWorkflowsDir(page);
        const seed = await seedAndTriggerRun(page, workflowsDir);
        try {
            // Mutate the seeded workflow.yaml in the workspace so it differs from source.
            const wsYaml = path.join(seed.workspacePath, '.workflow', 'workflow.yaml');
            const original = await fs.readFile(wsYaml, 'utf8');
            await fs.writeFile(wsYaml, original + '\n# pending edit\n', 'utf8');

            const pending = await fetchJson(page, `/api/runs/${seed.runId}/pending-changes`);
            expect(pending.changes.length).toBe(1);
            const change = pending.changes[0];
            expect(change.kind).toBe('modified');
            expect(change.workspace_path).toBe('.workflow/workflow.yaml');
            expect(change.diff).toContain('+# pending edit');

            await page.goto('/');
            await gotoRoute(page, `#/workflow/${seed.runId}`);
            const section = page.locator('#pending-workspace-changes');
            await expect(section).toBeAttached();
            // Wait for the first 3s pollInterval refresh to populate the section.
            await expect(section).not.toHaveAttribute('hidden', '', { timeout: 15_000 });
            await expect(section.locator('.pending-changes-row')).toHaveCount(1);
            await expect(section.locator('.pending-changes-diff .diff-add')).toContainText('# pending edit');
        } finally {
            await cleanupSeed(seed.workflowYamlPath);
        }
    });

    test('discard endpoint removes the workspace file', async ({ page }) => {
        const workflowsDir = await resolveWorkflowsDir(page);
        const seed = await seedAndTriggerRun(page, workflowsDir);
        try {
            const wsYaml = path.join(seed.workspacePath, '.workflow', 'workflow.yaml');
            const original = await fs.readFile(wsYaml, 'utf8');
            await fs.writeFile(wsYaml, original + '\n# pending edit\n', 'utf8');

            const discardResp = await page.request.post(
                `/api/runs/${seed.runId}/pending-changes/apply`,
                {
                    data: { workspace_path: '.workflow/workflow.yaml', action: 'discard' },
                },
            );
            expect(discardResp.ok(), `discard -> ${discardResp.status()}`).toBeTruthy();
            const body = await discardResp.json();
            expect(body.applied).toBe(true);

            // Workspace YAML should be gone (discard deletes, doesn't restore).
            let stillThere = true;
            try { await fs.stat(wsYaml); } catch { stillThere = false; }
            expect(stillThere).toBe(false);

            // Source YAML untouched, so iter_changes finds no diff and no new file.
            const pending = await fetchJson(page, `/api/runs/${seed.runId}/pending-changes`);
            expect(pending.changes).toEqual([]);
        } finally {
            await cleanupSeed(seed.workflowYamlPath);
        }
    });

    test('apply endpoint writes workspace content back to source', async ({ page }) => {
        const workflowsDir = await resolveWorkflowsDir(page);
        const seed = await seedAndTriggerRun(page, workflowsDir);
        try {
            const wsYaml = path.join(seed.workspacePath, '.workflow', 'workflow.yaml');
            const original = await fs.readFile(wsYaml, 'utf8');
            const mutated = original + '\n# pending edit\n';
            await fs.writeFile(wsYaml, mutated, 'utf8');

            const applyResp = await page.request.post(
                `/api/runs/${seed.runId}/pending-changes/apply`,
                {
                    data: { workspace_path: '.workflow/workflow.yaml', action: 'apply' },
                },
            );
            expect(applyResp.ok(), `apply -> ${applyResp.status()}`).toBeTruthy();
            const body = await applyResp.json();
            expect(body.applied).toBe(true);
            expect(body.source_path).toBe(seed.workflowYamlPath);

            const sourceText = await fs.readFile(seed.workflowYamlPath, 'utf8');
            expect(sourceText).toBe(mutated);
        } finally {
            await cleanupSeed(seed.workflowYamlPath);
        }
    });

    test('DOM-shape: PendingChanges global is defined and section is unique', async ({ page }) => {
        // Cheap shape-only test — no run seeding required. Navigate to a
        // non-existent run; the section is mounted regardless.
        await page.goto('/');
        await gotoRoute(page, '#/workflow/no-such-run');

        const shape = await page.evaluate(() => ({
            hasPendingChanges: typeof (window as any).PendingChanges === 'object',
            hasMount: typeof (window as any).PendingChanges?.mount === 'function',
            hasRefresh: typeof (window as any).PendingChanges?.refresh === 'function',
            hasUnmount: typeof (window as any).PendingChanges?.unmount === 'function',
            sectionCount: document.querySelectorAll('#pending-workspace-changes').length,
        }));

        expect(shape.hasPendingChanges).toBe(true);
        expect(shape.hasMount).toBe(true);
        expect(shape.hasRefresh).toBe(true);
        expect(shape.hasUnmount).toBe(true);
        // sectionCount may be 0 if the run-detail page didn't render (no run
        // found), or 1 if it did. The important regression is "never > 1".
        expect(shape.sectionCount).toBeLessThanOrEqual(1);
    });
});

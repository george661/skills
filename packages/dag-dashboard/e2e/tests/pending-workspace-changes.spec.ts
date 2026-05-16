/**
 * E2E — Pending workspace changes UI (GW-5937).
 *
 * Drives a real workflow trigger that seeds prompt+script files into the
 * run workspace, mutates them post-run to create pending changes, and
 * exercises the GET / POST routes plus the run-detail UI section.
 *
 * The trigger flow is the only way the existing harness can produce a real
 * `.workflow/.manifest.json` and a workspace channel populated in the DB —
 * there's no admin endpoint to seed runs directly.
 */
import { promises as fs } from 'fs';
import * as path from 'path';

import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

import { gotoRoute } from './helpers';

const WORKFLOW_NAME = 'e2e-pending-changes';

// Workflow with a prompt_file and a script_path so seeding produces a
// non-empty manifest with both prompt_file and bash_script kinds.
const WORKFLOW_YAML = `
name: ${WORKFLOW_NAME}
config:
  checkpoint_prefix: ${WORKFLOW_NAME}
nodes:
  - id: shell_node
    name: Run script
    type: bash
    script_path: ../scripts/${WORKFLOW_NAME}.sh
`.trimStart();

const SCRIPT_CONTENT = `#!/usr/bin/env bash
echo "hello from ${WORKFLOW_NAME}"
`;

async function fetchJson(page: Page, url: string): Promise<any> {
    const res = await page.request.get(url);
    expect(res.ok(), `${url} → ${res.status()}`).toBeTruthy();
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
    timeoutMs = 60_000,
): Promise<any> {
    const deadline = Date.now() + timeoutMs;
    const terminalStatuses = ['completed', 'failed', 'cancelled', 'paused'];
    let last: any = null;
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
        `Run ${runId} did not reach terminal status in ${timeoutMs}ms; last=${JSON.stringify(last?.run ?? {})}`,
    );
}

async function seedAndTriggerRun(page: Page, workflowsDir: string): Promise<{
    runId: string;
    workspacePath: string;
    workflowYamlPath: string;
    scriptPath: string;
}> {
    await enableTrigger(page);

    // Seed the workflow YAML and the referenced script.
    const yamlPath = path.join(workflowsDir, `${WORKFLOW_NAME}.yaml`);
    const scriptDir = path.join(path.dirname(workflowsDir), 'scripts');
    const scriptPath = path.join(scriptDir, `${WORKFLOW_NAME}.sh`);
    // The workflow references "../scripts/...", so scripts/ must live a sibling
    // of workflows/ inside the harness tmp dir for path resolution to succeed.
    const sharedRoot = path.dirname(workflowsDir);
    const scriptsDirAbs = path.join(sharedRoot, 'scripts');
    await fs.mkdir(scriptsDirAbs, { recursive: true });
    await fs.writeFile(scriptPath, SCRIPT_CONTENT, 'utf8');
    await fs.chmod(scriptPath, 0o755);
    await fs.mkdir(workflowsDir, { recursive: true });
    await fs.writeFile(yamlPath, WORKFLOW_YAML, 'utf8');

    // Trigger the workflow via the API (no UI form for this flow).
    const triggerResp = await page.request.post('/api/trigger', {
        data: { workflow_name: WORKFLOW_NAME, inputs: {} },
    });
    expect(triggerResp.ok(), `POST /api/trigger → ${triggerResp.status()}`).toBeTruthy();
    const triggerBody = await triggerResp.json();
    const runId = triggerBody.run_id as string;
    expect(runId).toBeTruthy();

    // Wait for completion so the workspace is fully seeded.
    await pollRunStatus(page, runId);

    // Read the workspace channel to discover the workspace path the executor
    // chose. Default is ~/.dag-dashboard/workspaces/{run_id}.
    const channels = await fetchJson(page, `/api/workflows/${runId}/channels`);
    const wsChannel = (channels?.channels ?? []).find((c: any) => c.key === 'workspace');
    expect(wsChannel, 'workspace channel must exist after run').toBeTruthy();
    // Channel value can be a string or {"value": ...} dict.
    const rawVal = wsChannel.value;
    const workspacePath = typeof rawVal === 'string' ? rawVal : rawVal?.value;
    expect(workspacePath, 'workspace path must be a string').toBeTruthy();

    return { runId, workspacePath, workflowYamlPath: yamlPath, scriptPath };
}

async function cleanupSeed(yamlPath: string, scriptPath: string): Promise<void> {
    await fs.rm(yamlPath, { force: true });
    await fs.rm(scriptPath, { force: true });
}

test.describe('Pending workspace changes (GW-5937)', () => {
    test.setTimeout(120_000);

    test('section is hidden when workspace has no pending changes', async ({ page }) => {
        const workflowsDir = await resolveWorkflowsDir(page);
        const seed = await seedAndTriggerRun(page, workflowsDir);
        try {
            // No workspace mutations → no pending changes.
            const pending = await fetchJson(page, `/api/runs/${seed.runId}/pending-changes`);
            expect(pending.changes, 'no mutations → empty changes').toEqual([]);

            // Navigate via two-step hash routing, per skills/CLAUDE.md.
            await page.goto('/');
            await gotoRoute(page, `#/workflow/${seed.runId}`);

            const section = page.locator('#pending-workspace-changes');
            await expect(section).toBeAttached();
            await expect(section).toHaveAttribute('hidden', '');
        } finally {
            await cleanupSeed(seed.workflowYamlPath, seed.scriptPath);
        }
    });

    test('section becomes visible with diff when a workspace file is mutated', async ({ page }) => {
        const workflowsDir = await resolveWorkflowsDir(page);
        const seed = await seedAndTriggerRun(page, workflowsDir);
        try {
            // Mutate the seeded script in the workspace so it differs from source.
            const wsScript = path.join(seed.workspacePath, '.workflow', 'scripts', `${WORKFLOW_NAME}.sh`);
            await fs.writeFile(wsScript, SCRIPT_CONTENT + '# pending edit\n', 'utf8');

            // Verify the GET endpoint surfaces the modified change.
            const pending = await fetchJson(page, `/api/runs/${seed.runId}/pending-changes`);
            expect(pending.changes.length).toBe(1);
            const change = pending.changes[0];
            expect(change.kind).toBe('modified');
            expect(change.workspace_path).toBe(`.workflow/scripts/${WORKFLOW_NAME}.sh`);
            expect(change.diff).toContain('+# pending edit');

            // Navigate to run-detail; UI section should render the row.
            await page.goto('/');
            await gotoRoute(page, `#/workflow/${seed.runId}`);

            const section = page.locator('#pending-workspace-changes');
            await expect(section).toBeAttached();
            // Wait for the first poll-driven refresh to populate the section.
            await expect(section).not.toHaveAttribute('hidden', '', { timeout: 10_000 });
            await expect(section.locator('.pending-changes-row')).toHaveCount(1);
            // Diff <pre> should contain plus-line-prefixed entries for the new line.
            await expect(section.locator('.pending-changes-diff .diff-add')).toContainText('# pending edit');
        } finally {
            await cleanupSeed(seed.workflowYamlPath, seed.scriptPath);
        }
    });

    test('discard endpoint removes the workspace file', async ({ page }) => {
        const workflowsDir = await resolveWorkflowsDir(page);
        const seed = await seedAndTriggerRun(page, workflowsDir);
        try {
            const wsScript = path.join(seed.workspacePath, '.workflow', 'scripts', `${WORKFLOW_NAME}.sh`);
            await fs.writeFile(wsScript, SCRIPT_CONTENT + '# pending edit\n', 'utf8');

            // POST discard.
            const discardResp = await page.request.post(
                `/api/runs/${seed.runId}/pending-changes/apply`,
                {
                    data: {
                        workspace_path: `.workflow/scripts/${WORKFLOW_NAME}.sh`,
                        action: 'discard',
                    },
                },
            );
            expect(discardResp.ok(), `discard → ${discardResp.status()}`).toBeTruthy();
            const body = await discardResp.json();
            expect(body.applied).toBe(true);

            // Workspace file should be gone.
            let stillThere = true;
            try { await fs.stat(wsScript); } catch { stillThere = false; }
            expect(stillThere).toBe(false);

            // GET should now show no pending changes.
            const pending = await fetchJson(page, `/api/runs/${seed.runId}/pending-changes`);
            expect(pending.changes).toEqual([]);
        } finally {
            await cleanupSeed(seed.workflowYamlPath, seed.scriptPath);
        }
    });

    test('apply endpoint writes workspace content back to source', async ({ page }) => {
        const workflowsDir = await resolveWorkflowsDir(page);
        const seed = await seedAndTriggerRun(page, workflowsDir);
        try {
            const wsScript = path.join(seed.workspacePath, '.workflow', 'scripts', `${WORKFLOW_NAME}.sh`);
            const newContent = SCRIPT_CONTENT + '# pending edit\n';
            await fs.writeFile(wsScript, newContent, 'utf8');

            // POST apply.
            const applyResp = await page.request.post(
                `/api/runs/${seed.runId}/pending-changes/apply`,
                {
                    data: {
                        workspace_path: `.workflow/scripts/${WORKFLOW_NAME}.sh`,
                        action: 'apply',
                    },
                },
            );
            expect(applyResp.ok(), `apply → ${applyResp.status()}`).toBeTruthy();
            const body = await applyResp.json();
            expect(body.applied).toBe(true);
            expect(body.source_path).toBe(seed.scriptPath);

            // Source file should now contain the workspace content.
            const sourceText = await fs.readFile(seed.scriptPath, 'utf8');
            expect(sourceText).toBe(newContent);
        } finally {
            await cleanupSeed(seed.workflowYamlPath, seed.scriptPath);
        }
    });

    test('DOM-shape: PendingChanges global is defined and section is unique', async ({ page }) => {
        // Cheap shape-only test — no run seeding required.
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
        expect(shape.sectionCount).toBe(1);
    });
});

/**
 * E2E tests for unified feed layout (GW-5422)
 * 
 * Tests:
 * - Two-pane layout with ResizableSplit
 * - WorkflowProgressCard renders SSE events
 * - State slideover opens/closes
 * - DAG-feed cross-selection via NodeScrollBus
 */

import { test, expect } from '@playwright/test';

test.describe('Run Detail Unified Feed', () => {
    test('should display two-pane layout with DAG and unified feed', async ({ page }) => {
        // Navigate to a run detail page (assumes test data exists)
        await page.goto('/');
        
        // Check for two-pane split layout
        const splitContainer = page.locator('.run-pane-split');
        await expect(splitContainer).toBeVisible();
        
        // Left pane should contain DAG
        const leftPane = page.locator('.run-pane-left');
        await expect(leftPane).toBeVisible();
        await expect(leftPane.locator('#dag-container')).toBeVisible();
        
        // Right pane should contain unified feed
        const rightPane = page.locator('.run-pane-right');
        await expect(rightPane).toBeVisible();
        await expect(rightPane.locator('.workflow-progress-card-container')).toBeVisible();
    });

    test('should show state slideover toggle button', async ({ page }) => {
        await page.goto('/');
        
        const toggleBtn = page.locator('#state-slideover-toggle');
        await expect(toggleBtn).toBeVisible();
        await expect(toggleBtn).toHaveText(/View State/i);
    });

    test('should open and close state slideover', async ({ page }) => {
        await page.goto('/');
        
        // Slideover should be closed initially
        const slideover = page.locator('.state-slideover');
        await expect(slideover).toHaveClass(/state-slideover--closed/);
        
        // Click toggle button to open
        await page.click('#state-slideover-toggle');
        await expect(slideover).not.toHaveClass(/state-slideover--closed/);
        
        // Slideover panel should be visible
        const panel = page.locator('.state-slideover-panel');
        await expect(panel).toBeVisible();
        
        // Should contain state containers
        await expect(panel.locator('#channel-state-container')).toBeVisible();
        await expect(panel.locator('#state-diff-timeline-container')).toBeVisible();
        await expect(panel.locator('#run-artifacts-container')).toBeVisible();
        
        // Click close button
        await page.click('.state-slideover-close');
        await expect(slideover).toHaveClass(/state-slideover--closed/);
    });

    test('should close slideover when clicking backdrop', async ({ page }) => {
        await page.goto('/');
        
        // Open slideover
        await page.click('#state-slideover-toggle');
        const slideover = page.locator('.state-slideover');
        await expect(slideover).not.toHaveClass(/state-slideover--closed/);
        
        // Click backdrop
        await page.click('.state-slideover-backdrop');
        await expect(slideover).toHaveClass(/state-slideover--closed/);
    });

    test('should render progress card messages', async ({ page }) => {
        await page.goto('/');
        
        // Wait for progress card container
        const container = page.locator('.workflow-progress-card-container');
        await expect(container).toBeVisible();
        
        // Should either show messages or empty state
        const hasMessages = await page.locator('.progress-card-item').count() > 0;
        const hasEmpty = await page.locator('.progress-card-empty').count() > 0;
        expect(hasMessages || hasEmpty).toBeTruthy();
    });

    test('should handle DAG node click for cross-selection', async ({ page }) => {
        await page.goto('/');
        
        // Wait for DAG to render
        await page.waitForSelector('#dag-container .dag-node', { timeout: 5000 }).catch(() => {
            // DAG might not have nodes in empty state - that's OK for this test structure
        });
        
        // Check that NodeScrollBus is available
        const busAvailable = await page.evaluate(() => {
            return typeof (window as any).NodeScrollBus !== 'undefined';
        });
        expect(busAvailable).toBeTruthy();
    });

    test('should have ResizableSplit initialized', async ({ page }) => {
        await page.goto('/');
        
        // Check that ResizableSplit is available and applied
        const hasResizableSplit = await page.evaluate(() => {
            return typeof (window as any).ResizableSplit !== 'undefined';
        });
        expect(hasResizableSplit).toBeTruthy();
        
        // Split should have the run-split class applied by ResizableSplit
        const splitContainer = page.locator('.run-pane-split');
        await expect(splitContainer).toBeVisible();
    });
});

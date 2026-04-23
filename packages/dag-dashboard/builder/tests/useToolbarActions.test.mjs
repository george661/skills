/**
 * useToolbarActions.test.mjs
 *
 * Tests the hook that wraps API calls: Save, Publish, Run, Validate.
 * Uses simple fetch mocking without external test libraries.
 */

import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert';
import React from 'react';
import TestRenderer from 'react-test-renderer';
import useToolbarActions from '../src/useToolbarActions.js';

// Test harness component to exercise the hook
function ToolbarActionsHarness({ workflowName, children }) {
  const actions = useToolbarActions(workflowName);
  return children(actions);
}

describe('useToolbarActions', () => {
  let fetchCalls = [];
  let originalFetch;

  beforeEach(() => {
    // Save original fetch and setup mock
    originalFetch = global.fetch;
    fetchCalls = [];

    global.fetch = async (url, options) => {
      fetchCalls.push({ url, options });

      // Mock responses based on URL
      if (url.includes('/drafts') && !url.includes('/publish')) {
        return {
          ok: true,
          json: async () => ({ timestamp: '123456789' }),
        };
      } else if (url.includes('/publish')) {
        return {
          ok: true,
          json: async () => ({ success: true }),
        };
      } else if (url.includes('/trigger')) {
        return {
          ok: true,
          json: async () => ({ run_id: 'RUN123' }),
        };
      } else if (url.includes('/validate')) {
        return {
          ok: true,
          json: async () => ({ errors: [], warnings: [] }),
        };
      }

      return { ok: true, json: async () => ({}) };
    };

    // Mock window.location.hash for navigation tests
    if (typeof window === 'undefined') {
      global.window = { location: { hash: '' } };
    } else {
      window.location.hash = '';
    }
  });

  afterEach(() => {
    // Restore original fetch
    global.fetch = originalFetch;
  });

  it('save_calls_drafts_endpoint', async () => {
    // Test that the save endpoint is called correctly
    const workflowName = 'test-workflow';
    const yaml = 'name: test-workflow\ndescription: test\n';

    let actions;
    TestRenderer.create(
      <ToolbarActionsHarness workflowName={workflowName}>
        {(a) => {
          actions = a;
          return null;
        }}
      </ToolbarActionsHarness>
    );

    const result = await actions.saveDraft(yaml);

    assert.strictEqual(fetchCalls.length, 1);
    assert.ok(fetchCalls[0].url.includes('/drafts'));
    assert.strictEqual(fetchCalls[0].options.method, 'POST');
    assert.strictEqual(result.timestamp, '123456789');
  });

  it('publish_uses_latest_timestamp', async () => {
    const workflowName = 'test-workflow';
    const yaml = 'name: test\n';

    let actions;
    TestRenderer.create(
      <ToolbarActionsHarness workflowName={workflowName}>
        {(a) => {
          actions = a;
          return null;
        }}
      </ToolbarActionsHarness>
    );

    // First save to set timestamp
    await actions.saveDraft(yaml);
    fetchCalls = []; // Reset to only track publish call

    // Now publish should use the saved timestamp
    await actions.publishDraft();

    assert.strictEqual(fetchCalls.length, 1);
    assert.ok(fetchCalls[0].url.includes('/publish'));
    assert.ok(fetchCalls[0].url.includes('123456789'));
  });

  it('run_sequence', async () => {
    // Test the complete run sequence: save -> publish -> trigger -> navigate
    const workflowName = 'test-workflow';
    const yaml = 'name: test\n';

    let actions;
    TestRenderer.create(
      <ToolbarActionsHarness workflowName={workflowName}>
        {(a) => {
          actions = a;
          return null;
        }}
      </ToolbarActionsHarness>
    );

    // Execute runWorkflow which should do save -> publish -> trigger
    const result = await actions.runWorkflow(yaml);

    // Should have called all three endpoints
    assert.strictEqual(fetchCalls.length, 3);
    assert.ok(fetchCalls[0].url.includes('/drafts'), 'First call should be save');
    assert.ok(fetchCalls[1].url.includes('/publish'), 'Second call should be publish');
    assert.ok(fetchCalls[2].url.includes('/trigger'), 'Third call should be trigger');
    assert.strictEqual(result.run_id, 'RUN123');

    // Should navigate to run detail page
    const expectedHash = '#/workflow/RUN123';
    assert.strictEqual(
      global.window?.location?.hash || window?.location?.hash,
      expectedHash,
      'Should navigate to run detail page'
    );
  });

  it('validate_returns_panel_response', async () => {
    const yaml = 'name: test\n';

    let actions;
    TestRenderer.create(
      <ToolbarActionsHarness workflowName="test-workflow">
        {(a) => {
          actions = a;
          return null;
        }}
      </ToolbarActionsHarness>
    );

    const result = await actions.validateWorkflow(yaml);

    assert.strictEqual(fetchCalls.length, 1);
    assert.ok(fetchCalls[0].url.includes('/validate'));
    assert.ok(Array.isArray(result.errors));
    assert.ok(Array.isArray(result.warnings));
  });
});

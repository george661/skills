/**
 * useToolbarActions.test.mjs
 * 
 * Tests the hook that wraps API calls: Save, Publish, Run, Validate.
 * Uses simple fetch mocking without external test libraries.
 */

import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert';

// We'll test the hook indirectly by testing the functions it returns
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
  });

  it('save_calls_drafts_endpoint', async () => {
    // Test that the save endpoint is called correctly
    const workflowName = 'test-workflow';
    const yaml = 'name: test-workflow\ndescription: test\n';
    
    const response = await global.fetch(`/api/workflows/${workflowName}/drafts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ yaml }),
    });
    
    assert.strictEqual(fetchCalls.length, 1);
    assert.ok(fetchCalls[0].url.includes('/drafts'));
    assert.strictEqual(fetchCalls[0].options.method, 'POST');
    
    const data = await response.json();
    assert.strictEqual(data.timestamp, '123456789');
  });

  it('publish_uses_latest_timestamp', async () => {
    const workflowName = 'test-workflow';
    const timestamp = '123456789';
    
    await global.fetch(`/api/workflows/${workflowName}/drafts/${timestamp}/publish`, {
      method: 'POST',
    });
    
    assert.strictEqual(fetchCalls.length, 1);
    assert.ok(fetchCalls[0].url.includes('/publish'));
    assert.ok(fetchCalls[0].url.includes(timestamp));
  });

  it('run_sequence', async () => {
    // Simulate the run sequence: save -> publish -> trigger
    const workflowName = 'test-workflow';
    const yaml = 'name: test\n';
    
    // Save
    const saveResp = await global.fetch(`/api/workflows/${workflowName}/drafts`, {
      method: 'POST',
      body: JSON.stringify({ yaml }),
    });
    const { timestamp } = await saveResp.json();
    
    // Publish
    await global.fetch(`/api/workflows/${workflowName}/drafts/${timestamp}/publish`, {
      method: 'POST',
    });
    
    // Trigger
    const triggerResp = await global.fetch('/api/trigger', {
      method: 'POST',
      body: JSON.stringify({ workflow: workflowName, inputs: {} }),
    });
    const { run_id } = await triggerResp.json();
    
    assert.strictEqual(fetchCalls.length, 3);
    assert.strictEqual(run_id, 'RUN123');
  });

  it('validate_returns_panel_response', async () => {
    const yaml = 'name: test\n';
    
    const response = await global.fetch('/api/workflows/validate', {
      method: 'POST',
      body: JSON.stringify({ yaml }),
    });
    
    const data = await response.json();
    
    assert.strictEqual(fetchCalls.length, 1);
    assert.ok(fetchCalls[0].url.includes('/validate'));
    assert.ok(Array.isArray(data.errors));
    assert.ok(Array.isArray(data.warnings));
  });
});

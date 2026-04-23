/**
 * useVersionDrawer.test.mjs
 *
 * Tests for useVersionDrawer hook with injectable fetch/confirm.
 * Test count: 5 cases.
 */

import { describe, it } from 'node:test';
import assert from 'node:assert';
import React from 'react';
import TestRenderer from 'react-test-renderer';
import useVersionDrawer from '../src/useVersionDrawer.js';

// Test harness component
function TestHarness({ workflowName, currentCanvasJson, options, hookRef }) {
  const hook = useVersionDrawer(workflowName, currentCanvasJson, options);
  if (hookRef) hookRef.current = hook;
  return null;
}

describe('useVersionDrawer', () => {
  it('fetches_list_on_open', async () => {
    let fetchCalled = false;
    const mockFetch = async (url) => {
      fetchCalled = true;
      assert.match(url, /\/api\/workflows\/test-workflow\/drafts$/);
      return {
        ok: true,
        json: async () => [{ timestamp: '2024-01-01T00:00:00Z', content: '{}' }],
      };
    };

    const hookRef = { current: null };
    TestRenderer.create(
      <TestHarness
        workflowName="test-workflow"
        currentCanvasJson="{}"
        options={{ fetch: mockFetch }}
        hookRef={hookRef}
      />
    );

    await TestRenderer.act(async () => {
      hookRef.current.open();
      // Wait for useEffect to trigger
      await new Promise(resolve => setTimeout(resolve, 50));
    });

    assert.ok(fetchCalled, 'fetch should be called when drawer opens');
  });

  it('handles_empty_list', async () => {
    const mockFetch = async () => ({
      ok: true,
      json: async () => [],
    });

    const hookRef = { current: null };
    TestRenderer.create(
      <TestHarness
        workflowName="test-workflow"
        currentCanvasJson="{}"
        options={{ fetch: mockFetch }}
        hookRef={hookRef}
      />
    );

    await TestRenderer.act(async () => {
      hookRef.current.open();
      await new Promise(resolve => setTimeout(resolve, 50));
    });

    assert.ok(Array.isArray(hookRef.current.drafts), 'drafts should be an array');
    assert.strictEqual(hookRef.current.drafts.length, 0, 'drafts should be empty');
  });

  it('handles_fetch_error', async () => {
    const mockFetch = async () => {
      throw new Error('Network error');
    };

    const hookRef = { current: null };
    TestRenderer.create(
      <TestHarness
        workflowName="test-workflow"
        currentCanvasJson="{}"
        options={{ fetch: mockFetch }}
        hookRef={hookRef}
      />
    );

    await TestRenderer.act(async () => {
      hookRef.current.open();
      await new Promise(resolve => setTimeout(resolve, 50));
    });

    // Should not crash, drafts remain empty
    assert.ok(Array.isArray(hookRef.current.drafts));
  });

  it('delete_confirmation_false_prevents_fetch', async () => {
    let deleteFetchCalled = false;
    const mockFetch = async (url, opts) => {
      if (opts?.method === 'DELETE') {
        deleteFetchCalled = true;
      }
      return { ok: true, json: async () => ({}) };
    };
    const mockConfirm = () => false; // User cancels

    const hookRef = { current: null };
    TestRenderer.create(
      <TestHarness
        workflowName="test-workflow"
        currentCanvasJson="{}"
        options={{ fetch: mockFetch, confirm: mockConfirm }}
        hookRef={hookRef}
      />
    );

    await TestRenderer.act(async () => {
      const result = await hookRef.current.handleDelete('2024-01-01T00:00:00Z');
      assert.strictEqual(result, false, 'handleDelete should return false when user cancels');
    });

    assert.ok(!deleteFetchCalled, 'DELETE fetch should NOT be called when confirm returns false');
  });

  it('restore_shows_alert_on_non_ok_response', async () => {
    let alertCalled = false;
    let alertMessage = '';
    global.alert = (msg) => {
      alertCalled = true;
      alertMessage = msg;
    };

    const mockFetch = async () => ({
      ok: false,
      status: 404,
    });

    const hookRef = { current: null };
    TestRenderer.create(
      <TestHarness
        workflowName="test-workflow"
        currentCanvasJson="{}"
        options={{ fetch: mockFetch }}
        hookRef={hookRef}
      />
    );

    await TestRenderer.act(async () => {
      const result = await hookRef.current.handleRestore('2024-01-01T00:00:00Z');
      assert.strictEqual(result, null, 'handleRestore should return null on non-ok response');
    });

    assert.ok(alertCalled, 'alert should be called on non-ok response');
    assert.match(alertMessage, /404/, 'alert message should include HTTP status');
  });
});

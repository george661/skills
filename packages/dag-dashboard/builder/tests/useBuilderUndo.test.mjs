import { test } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { create, act } from 'react-test-renderer';

import { useBuilderUndo } from '../src/useBuilderUndo.js';

// Harness that captures the latest hook state on every render
function harnessWith(initialState, opts, ref) {
    function Harness() {
        const undo = useBuilderUndo(initialState, opts);
        ref.current = undo;
        return null;
    }
    let root;
    act(() => { root = create(React.createElement(Harness)); });
    return root;
}

test('push adds new state and clears future; canUndo becomes true', () => {
    const ref = { current: null };
    const initial = { nodes: ['a'], edges: [] };
    const root = harnessWith(initial, {}, ref);
    
    assert.equal(ref.current.canUndo, false);
    assert.equal(ref.current.canRedo, false);
    assert.deepEqual(ref.current.state, initial);
    
    const next = { nodes: ['a', 'b'], edges: [] };
    act(() => { ref.current.push(next); });
    
    assert.equal(ref.current.canUndo, true);
    assert.equal(ref.current.canRedo, false);
    assert.deepEqual(ref.current.state, next);
    
    root.unmount();
});

test('undo returns to prior state; canRedo becomes true', () => {
    const ref = { current: null };
    const initial = { nodes: ['a'], edges: [] };
    const root = harnessWith(initial, {}, ref);
    
    const next = { nodes: ['a', 'b'], edges: [] };
    act(() => { ref.current.push(next); });
    assert.deepEqual(ref.current.state, next);
    assert.equal(ref.current.canUndo, true);
    
    act(() => { ref.current.undo(); });
    
    assert.deepEqual(ref.current.state, initial);
    assert.equal(ref.current.canUndo, false);
    assert.equal(ref.current.canRedo, true);
    
    root.unmount();
});

test('redo re-applies; after a fresh push, future is cleared', () => {
    const ref = { current: null };
    const initial = { nodes: ['a'], edges: [] };
    const root = harnessWith(initial, {}, ref);
    
    const second = { nodes: ['a', 'b'], edges: [] };
    act(() => { ref.current.push(second); });
    act(() => { ref.current.undo(); });
    
    assert.deepEqual(ref.current.state, initial);
    assert.equal(ref.current.canRedo, true);
    
    act(() => { ref.current.redo(); });
    
    assert.deepEqual(ref.current.state, second);
    assert.equal(ref.current.canRedo, false);
    assert.equal(ref.current.canUndo, true);
    
    // Now push a new state — future should clear
    const third = { nodes: ['a', 'b', 'c'], edges: [] };
    act(() => { ref.current.push(third); });
    
    assert.deepEqual(ref.current.state, third);
    assert.equal(ref.current.canRedo, false);
    assert.equal(ref.current.canUndo, true);
    
    // Undo twice should go back to initial, not through the discarded 'second'
    act(() => { ref.current.undo(); });
    assert.deepEqual(ref.current.state, second);
    act(() => { ref.current.undo(); });
    assert.deepEqual(ref.current.state, initial);
    
    root.unmount();
});

test('50-snapshot cap: push 60 distinct states; undo 60 times; verify only the last 50 are reachable', () => {
    const ref = { current: null };
    const initial = { nodes: [0], edges: [] };
    const root = harnessWith(initial, { limit: 50 }, ref);
    
    // Push 60 more states (total 61 including initial)
    for (let i = 1; i <= 60; i++) {
        act(() => { ref.current.push({ nodes: [i], edges: [] }); });
    }
    
    // Current state should be the 60th
    assert.deepEqual(ref.current.state, { nodes: [60], edges: [] });
    
    // Undo 60 times
    for (let i = 0; i < 60; i++) {
        if (ref.current.canUndo) {
            act(() => { ref.current.undo(); });
        }
    }
    
    // Should have only reached back to state 11 (the earliest 11 were dropped)
    // 61 states total - 50 limit = state 11 is the oldest reachable
    // After 60 undos from state 60, we should be at state 11
    assert.deepEqual(ref.current.state, { nodes: [11], edges: [] });
    assert.equal(ref.current.canUndo, false);
    
    root.unmount();
});

test('reset replaces current state and clears history', () => {
    const ref = { current: null };
    const initial = { nodes: ['a'], edges: [] };
    const root = harnessWith(initial, {}, ref);
    
    const second = { nodes: ['a', 'b'], edges: [] };
    act(() => { ref.current.push(second); });
    
    assert.equal(ref.current.canUndo, true);
    
    const newBaseline = { nodes: ['x'], edges: [] };
    act(() => { ref.current.reset(newBaseline); });
    
    assert.deepEqual(ref.current.state, newBaseline);
    assert.equal(ref.current.canUndo, false);
    assert.equal(ref.current.canRedo, false);
    
    root.unmount();
});

test('no-op undo when past empty; no-op redo when future empty', () => {
    const ref = { current: null };
    const initial = { nodes: ['a'], edges: [] };
    const root = harnessWith(initial, {}, ref);
    
    assert.equal(ref.current.canUndo, false);
    act(() => { ref.current.undo(); });
    assert.deepEqual(ref.current.state, initial); // unchanged
    
    assert.equal(ref.current.canRedo, false);
    act(() => { ref.current.redo(); });
    assert.deepEqual(ref.current.state, initial); // unchanged
    
    root.unmount();
});

test('state reference-equality: same object push is no-op; new wrapper with same refs is NOT a no-op', () => {
    const ref = { current: null };
    const initial = { nodes: ['a'], edges: [] };
    const root = harnessWith(initial, {}, ref);
    
    // Push the exact same reference — should be no-op
    act(() => { ref.current.push(ref.current.state); });
    assert.equal(ref.current.canUndo, false); // no history created
    
    // Push a new wrapper with same inner arrays
    const newWrapper = { nodes: initial.nodes, edges: initial.edges };
    act(() => { ref.current.push(newWrapper); });
    
    // This SHOULD create history (different wrapper object)
    assert.equal(ref.current.canUndo, true);
    
    root.unmount();
});

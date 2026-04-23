import { test } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { create, act } from 'react-test-renderer';

import { useCanvasState } from '../src/useCanvasState.js';

// Harness that captures the latest hook state on every render via a ref
// callback, so tests can assert on state AFTER subsequent act() calls.
function harnessWith(initialDag, ref) {
    function Harness() {
        const state = useCanvasState(initialDag);
        ref.current = state;
        return null;
    }
    let root;
    act(() => { root = create(React.createElement(Harness)); });
    return root;
}

test('onConnect appends depends_on via an edge', () => {
    const ref = { current: null };
    const root = harnessWith([{ id: 'a' }, { id: 'b' }], ref);
    assert.equal(ref.current.edges.length, 0);

    act(() => { ref.current.onConnect({ source: 'a', target: 'b' }); });

    assert.equal(ref.current.edges.length, 1);
    assert.equal(ref.current.edges[0].source, 'a');
    assert.equal(ref.current.edges[0].target, 'b');
    const dag = ref.current.toDag();
    const b = dag.find(n => n.id === 'b');
    assert.deepEqual(b.depends_on, ['a']);
    root.unmount();
});

test('onNodesDelete removes node and incident edges, undo restores', () => {
    const ref = { current: null };
    const root = harnessWith(
        [{ id: 'a' }, { id: 'b', depends_on: ['a'] }, { id: 'c', depends_on: ['b'] }],
        ref,
    );
    assert.equal(ref.current.nodes.length, 3);
    assert.equal(ref.current.edges.length, 2);

    // Delete 'b' — should remove both incident edges (a→b, b→c)
    act(() => { ref.current.onNodesDelete([{ id: 'b' }]); });
    assert.equal(ref.current.nodes.length, 2);
    assert.equal(ref.current.edges.length, 0);
    assert.ok(!ref.current.nodes.some(n => n.id === 'b'));

    // Undo restores the deletion
    act(() => { ref.current.undo(); });
    assert.equal(ref.current.nodes.length, 3);
    assert.equal(ref.current.edges.length, 2);
    assert.ok(ref.current.nodes.some(n => n.id === 'b'));
    root.unmount();
});

test('onDrop creates a new node from NodeLibrary drag-data format', () => {
    const ref = { current: null };
    const root = harnessWith([], ref);
    const dragData = JSON.stringify({ kind: 'node-type', payload: { name: 'bash' } });
    const event = {
        preventDefault: () => {},
        clientX: 120,
        clientY: 80,
        dataTransfer: {
            getData: (key) => (key === 'application/x-dag-node' ? dragData : ''),
        },
    };

    act(() => { ref.current.onDrop(event); });

    assert.equal(ref.current.nodes.length, 1);
    const added = ref.current.nodes[0];
    assert.equal(added.data.node_type, 'bash');
    assert.equal(added.position.x, 120);
    assert.equal(added.position.y, 80);
    root.unmount();
});

test('onDrop also accepts bare dag-node-type string format', () => {
    const ref = { current: null };
    const root = harnessWith([], ref);
    const event = {
        preventDefault: () => {},
        clientX: 0,
        clientY: 0,
        dataTransfer: {
            getData: (key) => (key === 'application/x-dag-node-type' ? 'prompt' : ''),
        },
    };

    act(() => { ref.current.onDrop(event); });

    assert.equal(ref.current.nodes.length, 1);
    assert.equal(ref.current.nodes[0].data.node_type, 'prompt');
    root.unmount();
});

test('onConnect refuses self-loops and duplicates', () => {
    const ref = { current: null };
    const root = harnessWith([{ id: 'a' }, { id: 'b' }], ref);

    act(() => { ref.current.onConnect({ source: 'a', target: 'a' }); });
    assert.equal(ref.current.edges.length, 0);

    act(() => { ref.current.onConnect({ source: 'a', target: 'b' }); });
    act(() => { ref.current.onConnect({ source: 'a', target: 'b' }); });
    assert.equal(ref.current.edges.length, 1);
    root.unmount();
});

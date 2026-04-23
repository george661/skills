import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    dagToReactFlow,
    reactFlowToDag,
    applyDagreLayout,
} from '../src/dagToReactFlow.js';

test('dagToReactFlow returns empty graph for empty input', () => {
    assert.deepEqual(dagToReactFlow([]), { nodes: [], edges: [] });
});

test('dagToReactFlow handles a single node with no edges', () => {
    const out = dagToReactFlow([{ id: 'a', type: 'bash', name: 'first' }]);
    assert.equal(out.nodes.length, 1);
    assert.equal(out.edges.length, 0);
    assert.equal(out.nodes[0].id, 'a');
    assert.equal(out.nodes[0].data.node_type, 'bash');
    assert.equal(out.nodes[0].data.name, 'first');
});

test('depends_on populates edges source→target', () => {
    const dag = [
        { id: 'a', type: 'bash' },
        { id: 'b', type: 'bash', depends_on: ['a'] },
    ];
    const out = dagToReactFlow(dag);
    assert.equal(out.edges.length, 1);
    assert.deepEqual(
        { source: out.edges[0].source, target: out.edges[0].target },
        { source: 'a', target: 'b' },
    );
});

test('reactFlowToDag roundtrip preserves id, type, and depends_on', () => {
    const dag = [
        { id: 'a', type: 'bash', script: 'echo hi' },
        { id: 'b', type: 'prompt', prompt: 'say hi', depends_on: ['a'] },
    ];
    const rf = dagToReactFlow(dag);
    const back = reactFlowToDag(rf);
    assert.equal(back.length, 2);
    const a = back.find(n => n.id === 'a');
    const b = back.find(n => n.id === 'b');
    assert.equal(a.type, 'bash');
    assert.equal(a.script, 'echo hi');
    assert.equal(b.type, 'prompt');
    assert.deepEqual(b.depends_on, ['a']);
});

test('applyDagreLayout assigns numeric positions to all nodes', () => {
    const { nodes, edges } = applyDagreLayout(
        dagToReactFlow([
            { id: 'a' },
            { id: 'b', depends_on: ['a'] },
            { id: 'c', depends_on: ['b'] },
        ]),
    );
    assert.equal(nodes.length, 3);
    assert.equal(edges.length, 2);
    for (const n of nodes) {
        assert.equal(typeof n.position.x, 'number');
        assert.equal(typeof n.position.y, 'number');
        assert.ok(Number.isFinite(n.position.x));
        assert.ok(Number.isFinite(n.position.y));
    }
});

test('applyDagreLayout respects TB direction (parent y < child y)', () => {
    const { nodes } = applyDagreLayout(
        dagToReactFlow([
            { id: 'parent' },
            { id: 'child', depends_on: ['parent'] },
        ]),
    );
    const parent = nodes.find(n => n.id === 'parent');
    const child = nodes.find(n => n.id === 'child');
    assert.ok(parent.position.y < child.position.y, 'parent should be above child in TB layout');
});

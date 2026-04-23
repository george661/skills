import { test } from 'node:test';
import assert from 'node:assert/strict';

import { dagToReactFlow, applyDagreLayout } from '../src/dagToReactFlow.js';

/**
 * Performance test for the 50-node layout acceptance criterion
 * (PRP-PLAT-008: "50-node fixture renders in <500ms with Dagre layout").
 *
 * We measure only `applyDagreLayout` on a 50-node DAG — the dominant cost.
 * Full render/paint measurement requires a browser and is deferred to
 * a later E2E task.
 *
 * Strategy: 5 warm-up runs (discarded to let V8 JIT stabilize), then 11
 * timed runs; assert the P50 is below the budget. This keeps the gate
 * deterministic across different CI runners.
 */

const BUDGET_MS = 500;
const WARMUP_RUNS = 5;
const TIMED_RUNS = 11;

function build50NodeTree() {
    // Branching factor 3: 1 root + 3 + 9 + 27 = 40; add 10 leaf children.
    const nodes = [{ id: 'n0' }];
    for (let i = 1; i <= 3; i += 1) nodes.push({ id: `n${i}`, depends_on: ['n0'] });
    let counter = 4;
    for (let layer = 0; layer < 2; layer += 1) {
        const parentStart = layer === 0 ? 1 : 4;
        const parentEnd = layer === 0 ? 3 : 12;
        for (let p = parentStart; p <= parentEnd; p += 1) {
            for (let c = 0; c < 3 && counter < 40; c += 1) {
                nodes.push({ id: `n${counter}`, depends_on: [`n${p}`] });
                counter += 1;
            }
        }
    }
    let leafParent = 13;
    while (nodes.length < 50) {
        nodes.push({ id: `n${counter}`, depends_on: [`n${leafParent}`] });
        counter += 1;
        leafParent += 1;
    }
    return nodes;
}

test('50-node Dagre layout P50 is under 500ms', () => {
    const dag = build50NodeTree();
    assert.equal(dag.length, 50);
    const rf = dagToReactFlow(dag);

    // Warm-up
    for (let i = 0; i < WARMUP_RUNS; i += 1) {
        applyDagreLayout(rf);
    }

    // Timed
    const samples = [];
    for (let i = 0; i < TIMED_RUNS; i += 1) {
        const t0 = process.hrtime.bigint();
        applyDagreLayout(rf);
        const t1 = process.hrtime.bigint();
        samples.push(Number(t1 - t0) / 1e6);
    }
    samples.sort((a, b) => a - b);
    const p50 = samples[Math.floor(samples.length / 2)];
    // Document result for PR description
    console.log(`[perf] 50-node applyDagreLayout P50 = ${p50.toFixed(2)}ms (budget ${BUDGET_MS}ms)`);

    assert.ok(p50 < BUDGET_MS, `P50 layout time ${p50.toFixed(2)}ms exceeds ${BUDGET_MS}ms budget`);
});

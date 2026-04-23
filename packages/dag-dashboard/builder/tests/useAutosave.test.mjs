import { test } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { create, act } from 'react-test-renderer';

import { useAutosave } from '../src/useAutosave.js';

// Controllable clock for testing debounce
class FakeClock {
    constructor() {
        this.time = 0;
        this.timers = [];
    }

    setTimeout(fn, delay) {
        const id = this.timers.length;
        this.timers.push({ id, fn, delay, fireAt: this.time + delay });
        return id;
    }

    clearTimeout(id) {
        this.timers = this.timers.filter(t => t.id !== id);
    }

    tick(ms) {
        this.time += ms;
        const toFire = this.timers.filter(t => t.fireAt <= this.time);
        this.timers = this.timers.filter(t => t.fireAt > this.time);
        toFire.forEach(t => t.fn());
    }
}

// Harness that captures the latest hook state
function harnessWith(options, ref) {
    function Harness() {
        const state = useAutosave(options);
        ref.current = state;
        return null;
    }
    let root;
    act(() => { root = create(React.createElement(Harness)); });
    return root;
}

test('bootstrap creates new draft and sets .current when GET /current is 404', async () => {
    const calls = [];
    const mockFetch = (url, opts) => {
        calls.push({ url, opts });
        if (url.endsWith('/drafts/current')) {
            return Promise.resolve({ ok: false, status: 404 });
        }
        if (url.endsWith('/drafts') && opts?.method === 'POST') {
            return Promise.resolve({
                ok: true,
                status: 201,
                json: () => Promise.resolve({ timestamp: '20260101T120000_000000Z' })
            });
        }
        if (url.includes('/drafts/current') && opts?.method === 'PUT') {
            return Promise.resolve({ ok: true, status: 204 });
        }
        return Promise.resolve({ ok: false, status: 500 });
    };

    const ref = { current: null };
    const getDag = () => [];
    await act(async () => {
        harnessWith({ workflowName: 'test', getDag, fetch: mockFetch }, ref);
        await new Promise(resolve => setTimeout(resolve, 10));
    });

    // Verify POST to create draft, then PUT to set .current
    assert.ok(calls.some(c => c.url.endsWith('/drafts') && c.opts?.method === 'POST'));
    assert.ok(calls.some(c => c.url.includes('/drafts/current') && c.opts?.method === 'PUT'));
    assert.equal(ref.current.currentTimestamp, '20260101T120000_000000Z');
});

test('bootstrap loads existing draft when GET /current returns 200', async () => {
    const calls = [];
    const mockFetch = (url, opts) => {
        calls.push({ url, opts });
        if (url.endsWith('/drafts/current') && !opts?.method) {
            return Promise.resolve({
                ok: true,
                status: 200,
                json: () => Promise.resolve({ timestamp: '20260102T120000_000000Z' })
            });
        }
        if (url.includes('/20260102T120000_000000Z') && !opts?.method) {
            return Promise.resolve({
                ok: true,
                status: 200,
                json: () => Promise.resolve({ content: '{"nodes":[]}' })
            });
        }
        return Promise.resolve({ ok: false, status: 500 });
    };

    const ref = { current: null };
    const getDag = () => [];
    const onLoad = (dag) => { calls.push({ onLoad: dag }); };
    
    await act(async () => {
        harnessWith({ workflowName: 'test', getDag, fetch: mockFetch, onLoad }, ref);
        await new Promise(resolve => setTimeout(resolve, 10));
    });

    // Verify GET /current, then GET the draft, then onLoad called
    assert.ok(calls.some(c => c.url.endsWith('/drafts/current')));
    assert.ok(calls.some(c => c.url.includes('/20260102T120000_000000Z')));
    assert.ok(calls.some(c => c.onLoad !== undefined));
    assert.equal(ref.current.currentTimestamp, '20260102T120000_000000Z');
});

test('autosave fires PUT /drafts/<ts> after delayMs of inactivity', async () => {
    const clock = new FakeClock();
    const calls = [];
    const mockFetch = (url, opts) => {
        calls.push({ url, opts });
        if (url.endsWith('/drafts/current')) {
            return Promise.resolve({ ok: false, status: 404 });
        }
        if (url.endsWith('/drafts') && opts?.method === 'POST') {
            return Promise.resolve({
                ok: true,
                status: 201,
                json: () => Promise.resolve({ timestamp: '20260101T120000_000000Z' })
            });
        }
        if (opts?.method === 'PUT') {
            return Promise.resolve({ ok: true, status: 204 });
        }
        return Promise.resolve({ ok: false, status: 500 });
    };

    const ref = { current: null };
    let dagValue = [];
    const getDag = () => dagValue;

    let root;
    await act(async () => {
        root = harnessWith({
            workflowName: 'test',
            getDag,
            fetch: mockFetch,
            delayMs: 30000,
            setTimer: clock.setTimeout.bind(clock),
            clearTimer: clock.clearTimeout.bind(clock)
        }, ref);
        await new Promise(resolve => setTimeout(resolve, 10));
    });

    // Simulate edit by changing dag
    dagValue = [{ id: 'a' }];
    act(() => { ref.current.markDirty(); });

    const putsBefore = calls.filter(c => c.url.includes('/drafts/') && c.opts?.method === 'PUT' && c.url.includes('20260101T120000_000000Z')).length;

    // Fire the timer (autosave is async so we need to wait for promises to resolve)
    await act(async () => {
        clock.tick(30000);
        await new Promise(resolve => setTimeout(resolve, 10));
    });

    // Verify PUT was called
    const putsAfter = calls.filter(c => c.url.includes('/drafts/') && c.opts?.method === 'PUT' && c.url.includes('20260101T120000_000000Z')).length;
    assert.ok(putsAfter > putsBefore, 'PUT should have been called after delayMs');

    root.unmount();
});

test('autosave does NOT fire before delayMs elapses', async () => {
    const clock = new FakeClock();
    const calls = [];
    const mockFetch = (url, opts) => {
        calls.push({ url, opts });
        if (url.endsWith('/drafts/current')) {
            return Promise.resolve({ ok: false, status: 404 });
        }
        if (url.endsWith('/drafts') && opts?.method === 'POST') {
            return Promise.resolve({
                ok: true,
                status: 201,
                json: () => Promise.resolve({ timestamp: '20260101T120000_000000Z' })
            });
        }
        if (opts?.method === 'PUT') {
            return Promise.resolve({ ok: true, status: 204 });
        }
        return Promise.resolve({ ok: false, status: 500 });
    };

    const ref = { current: null };
    let dagValue = [];
    const getDag = () => dagValue;

    let root;
    await act(async () => {
        root = harnessWith({
            workflowName: 'test',
            getDag,
            fetch: mockFetch,
            delayMs: 30000,
            setTimer: clock.setTimeout.bind(clock),
            clearTimer: clock.clearTimeout.bind(clock)
        }, ref);
        await new Promise(resolve => setTimeout(resolve, 10));
    });

    dagValue = [{ id: 'a' }];
    act(() => { ref.current.markDirty(); });

    const putsBefore = calls.filter(c => c.url.includes('/drafts/') && c.opts?.method === 'PUT' && c.url.includes('20260101T120000_000000Z')).length;

    // Advance time but not enough to fire
    await act(async () => {
        clock.tick(20000);
        await new Promise(resolve => setTimeout(resolve, 10));
    });

    const putsAfter = calls.filter(c => c.url.includes('/drafts/') && c.opts?.method === 'PUT' && c.url.includes('20260101T120000_000000Z')).length;
    assert.equal(putsAfter, putsBefore, 'PUT should NOT fire before delayMs');

    root.unmount();
});

test('autosave timer resets on each edit — only one PUT after quiet period', async () => {
    const clock = new FakeClock();
    const calls = [];
    const mockFetch = (url, opts) => {
        calls.push({ url, opts });
        if (url.endsWith('/drafts/current')) {
            return Promise.resolve({ ok: false, status: 404 });
        }
        if (url.endsWith('/drafts') && opts?.method === 'POST') {
            return Promise.resolve({
                ok: true,
                status: 201,
                json: () => Promise.resolve({ timestamp: '20260101T120000_000000Z' })
            });
        }
        if (opts?.method === 'PUT') {
            return Promise.resolve({ ok: true, status: 204 });
        }
        return Promise.resolve({ ok: false, status: 500 });
    };

    const ref = { current: null };
    let dagValue = [];
    const getDag = () => dagValue;

    let root;
    await act(async () => {
        root = harnessWith({
            workflowName: 'test',
            getDag,
            fetch: mockFetch,
            delayMs: 30000,
            setTimer: clock.setTimeout.bind(clock),
            clearTimer: clock.clearTimeout.bind(clock)
        }, ref);
        await new Promise(resolve => setTimeout(resolve, 10));
    });

    // Three edits spaced 10s apart
    dagValue = [{ id: 'a' }];
    act(() => { ref.current.markDirty(); });
    await act(async () => {
        clock.tick(10000);
        await new Promise(resolve => setTimeout(resolve, 5));
    });

    dagValue = [{ id: 'a' }, { id: 'b' }];
    act(() => { ref.current.markDirty(); });
    await act(async () => {
        clock.tick(10000);
        await new Promise(resolve => setTimeout(resolve, 5));
    });

    dagValue = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
    act(() => { ref.current.markDirty(); });
    
    // Now wait 30s from last edit
    await act(async () => {
        clock.tick(30000);
        await new Promise(resolve => setTimeout(resolve, 10));
    });

    // Count PUTs to the timestamp (excluding pointer updates)
    const puts = calls.filter(c => 
        c.url.includes('/drafts/') && 
        c.opts?.method === 'PUT' && 
        c.url.includes('20260101T120000_000000Z') &&
        !c.url.includes('/current')
    );
    assert.equal(puts.length, 1, 'Should only have 1 PUT after quiet period');

    root.unmount();
});

test('forceSave creates new timestamp via POST and repoints .current', async () => {
    const calls = [];
    let nextTimestamp = '20260101T120000_000000Z';
    const mockFetch = (url, opts) => {
        calls.push({ url, opts });
        if (url.endsWith('/drafts/current') && !opts?.method) {
            return Promise.resolve({ ok: false, status: 404 });
        }
        if (url.endsWith('/drafts') && opts?.method === 'POST') {
            const ts = nextTimestamp;
            nextTimestamp = '20260102T120000_000000Z';
            return Promise.resolve({
                ok: true,
                status: 201,
                json: () => Promise.resolve({ timestamp: ts })
            });
        }
        if (opts?.method === 'PUT') {
            return Promise.resolve({ ok: true, status: 204 });
        }
        return Promise.resolve({ ok: false, status: 500 });
    };

    const ref = { current: null };
    const getDag = () => [];

    await act(async () => {
        harnessWith({ workflowName: 'test', getDag, fetch: mockFetch }, ref);
        await new Promise(resolve => setTimeout(resolve, 10));
    });

    const initialTimestamp = ref.current.currentTimestamp;

    // Call forceSave
    await act(async () => {
        await ref.current.forceSave();
    });

    // Verify a new POST was made and .current was updated
    const posts = calls.filter(c => c.url.endsWith('/drafts') && c.opts?.method === 'POST');
    assert.ok(posts.length >= 2, 'Should have at least 2 POSTs (bootstrap + forceSave)');
    assert.notEqual(ref.current.currentTimestamp, initialTimestamp, 'Timestamp should change after forceSave');
});

test('forceSave inside the debounce window still creates a new timestamp', async () => {
    const clock = new FakeClock();
    const calls = [];
    let nextTimestamp = '20260101T120000_000000Z';
    const mockFetch = (url, opts) => {
        calls.push({ url, opts });
        if (url.endsWith('/drafts/current') && !opts?.method) {
            return Promise.resolve({ ok: false, status: 404 });
        }
        if (url.endsWith('/drafts') && opts?.method === 'POST') {
            const ts = nextTimestamp;
            if (nextTimestamp === '20260101T120000_000000Z') {
                nextTimestamp = '20260102T120000_000000Z';
            }
            return Promise.resolve({
                ok: true,
                status: 201,
                json: () => Promise.resolve({ timestamp: ts })
            });
        }
        if (opts?.method === 'PUT') {
            return Promise.resolve({ ok: true, status: 204 });
        }
        return Promise.resolve({ ok: false, status: 500 });
    };

    const ref = { current: null };
    let dagValue = [];
    const getDag = () => dagValue;

    await act(async () => {
        harnessWith({
            workflowName: 'test',
            getDag,
            fetch: mockFetch,
            delayMs: 30000,
            setTimer: clock.setTimeout.bind(clock),
            clearTimer: clock.clearTimeout.bind(clock)
        }, ref);
        await new Promise(resolve => setTimeout(resolve, 10));
    });

    const initialTimestamp = ref.current.currentTimestamp;

    // Trigger autosave debounce
    dagValue = [{ id: 'a' }];
    act(() => { ref.current.markDirty(); });

    // Wait only 10s (less than 30s)
    await act(async () => {
        clock.tick(10000);
        await new Promise(resolve => setTimeout(resolve, 5));
    });

    // Call forceSave
    await act(async () => {
        await ref.current.forceSave();
    });

    // Verify timestamp changed
    assert.notEqual(ref.current.currentTimestamp, initialTimestamp, 'forceSave should create new timestamp even within debounce window');
    assert.equal(ref.current.currentTimestamp, '20260102T120000_000000Z');
});

test('PUTs go to the same timestamp across multiple autosave cycles', async () => {
    const clock = new FakeClock();
    const calls = [];
    const mockFetch = (url, opts) => {
        calls.push({ url, opts });
        if (url.endsWith('/drafts/current')) {
            return Promise.resolve({ ok: false, status: 404 });
        }
        if (url.endsWith('/drafts') && opts?.method === 'POST') {
            return Promise.resolve({
                ok: true,
                status: 201,
                json: () => Promise.resolve({ timestamp: '20260101T120000_000000Z' })
            });
        }
        if (opts?.method === 'PUT') {
            return Promise.resolve({ ok: true, status: 204 });
        }
        return Promise.resolve({ ok: false, status: 500 });
    };

    const ref = { current: null };
    let dagValue = [];
    const getDag = () => dagValue;

    let root;
    await act(async () => {
        root = harnessWith({
            workflowName: 'test',
            getDag,
            fetch: mockFetch,
            delayMs: 30000,
            setTimer: clock.setTimeout.bind(clock),
            clearTimer: clock.clearTimeout.bind(clock)
        }, ref);
        await new Promise(resolve => setTimeout(resolve, 10));
    });

    // First autosave cycle
    dagValue = [{ id: 'a' }];
    act(() => { ref.current.markDirty(); });
    await act(async () => {
        clock.tick(30000);
        await new Promise(resolve => setTimeout(resolve, 10));
    });

    // Second autosave cycle (different dag)
    dagValue = [{ id: 'a' }, { id: 'b' }];
    act(() => { ref.current.markDirty(); });
    await act(async () => {
        clock.tick(30000);
        await new Promise(resolve => setTimeout(resolve, 10));
    });

    // Verify all PUTs went to the same timestamp
    const puts = calls.filter(c => 
        c.url.includes('/drafts/') && 
        c.opts?.method === 'PUT' && 
        !c.url.includes('/current')
    );
    
    assert.ok(puts.length >= 2, 'Should have at least 2 autosave PUTs');
    const timestamps = puts.map(p => {
        const match = p.url.match(/\/drafts\/([^/]+)$/);
        return match ? match[1] : null;
    });
    
    // All PUTs should be to the same timestamp
    assert.ok(timestamps.every(t => t === '20260101T120000_000000Z'), 
        'All autosave PUTs should go to the same timestamp (no explosion)');

    root.unmount();
});

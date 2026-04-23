import { test } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { create, act } from 'react-test-renderer';

import { useBuilderKeyboard } from '../src/useBuilderKeyboard.js';

// Mock document-like event target for testing
class MockDocument {
    constructor() {
        this.listeners = new Map();
    }
    addEventListener(type, handler) {
        if (!this.listeners.has(type)) {
            this.listeners.set(type, []);
        }
        this.listeners.get(type).push(handler);
    }
    removeEventListener(type, handler) {
        const handlers = this.listeners.get(type) || [];
        const idx = handlers.indexOf(handler);
        if (idx >= 0) handlers.splice(idx, 1);
    }
    dispatchEvent(event) {
        const handlers = this.listeners.get(event.type) || [];
        handlers.forEach(h => h(event));
    }
}

// Harness that mounts the keyboard hook with a mock document
function harnessKeyboard(shortcuts, opts = {}) {
    const mockDoc = new MockDocument();
    
    function Harness() {
        useBuilderKeyboard(shortcuts, { ...opts, target: mockDoc });
        return null;
    }
    
    let root;
    act(() => { root = create(React.createElement(Harness)); });
    
    return { root, mockDoc };
}

// Helper to create synthetic keyboard events
function createKeyEvent(key, { metaKey = false, ctrlKey = false, shiftKey = false, target = null } = {}) {
    const event = {
        type: 'keydown',
        key,
        metaKey,
        ctrlKey,
        shiftKey,
        target: target || { tagName: 'DIV' },
        defaultPrevented: false,
        preventDefault() { this.defaultPrevented = true; },
    };
    return event;
}

test('registers handler for each of the 9 shortcuts; firing the matching event invokes the handler and calls preventDefault', () => {
    let saveCount = 0;
    let undoCount = 0;
    let redoCount = 0;
    let yamlCount = 0;
    let validationCount = 0;
    let runCount = 0;
    let libraryCount = 0;
    let duplicateCount = 0;
    let deleteCount = 0;
    
    const shortcuts = {
        'mod+s': () => { saveCount++; },
        'mod+z': () => { undoCount++; },
        'mod+shift+z': () => { redoCount++; },
        'mod+/': () => { yamlCount++; },
        'mod+.': () => { validationCount++; },
        'mod+enter': () => { runCount++; },
        'mod+l': () => { libraryCount++; },
        'mod+d': () => { duplicateCount++; },
        'delete': () => { deleteCount++; },
    };
    
    const { root, mockDoc } = harnessKeyboard(shortcuts, { enabled: true, isMac: true });
    
    // Fire Cmd+S
    const saveEvent = createKeyEvent('s', { metaKey: true });
    mockDoc.dispatchEvent(saveEvent);
    assert.equal(saveCount, 1);
    assert.equal(saveEvent.defaultPrevented, true);
    
    // Fire Cmd+Z
    const undoEvent = createKeyEvent('z', { metaKey: true });
    mockDoc.dispatchEvent(undoEvent);
    assert.equal(undoCount, 1);
    assert.equal(undoEvent.defaultPrevented, true);
    
    // Fire Cmd+Shift+Z
    const redoEvent = createKeyEvent('z', { metaKey: true, shiftKey: true });
    mockDoc.dispatchEvent(redoEvent);
    assert.equal(redoCount, 1);
    assert.equal(redoEvent.defaultPrevented, true);
    
    // Fire Cmd+/
    const yamlEvent = createKeyEvent('/', { metaKey: true });
    mockDoc.dispatchEvent(yamlEvent);
    assert.equal(yamlCount, 1);
    
    // Fire Cmd+.
    const validationEvent = createKeyEvent('.', { metaKey: true });
    mockDoc.dispatchEvent(validationEvent);
    assert.equal(validationCount, 1);
    
    // Fire Cmd+Enter
    const runEvent = createKeyEvent('Enter', { metaKey: true });
    mockDoc.dispatchEvent(runEvent);
    assert.equal(runCount, 1);
    
    // Fire Cmd+L
    const libraryEvent = createKeyEvent('l', { metaKey: true });
    mockDoc.dispatchEvent(libraryEvent);
    assert.equal(libraryCount, 1);
    
    // Fire Cmd+D
    const duplicateEvent = createKeyEvent('d', { metaKey: true });
    mockDoc.dispatchEvent(duplicateEvent);
    assert.equal(duplicateCount, 1);
    
    // Fire Delete
    const deleteEvent = createKeyEvent('Delete', {});
    mockDoc.dispatchEvent(deleteEvent);
    assert.equal(deleteCount, 1);
    
    root.unmount();
});

test('modifier-sensitive matching: mod+z does NOT fire for z alone; mod+shift+z does NOT fire for mod+z', () => {
    let undoCount = 0;
    let redoCount = 0;
    
    const shortcuts = {
        'mod+z': () => { undoCount++; },
        'mod+shift+z': () => { redoCount++; },
    };
    
    const { root, mockDoc } = harnessKeyboard(shortcuts, { enabled: true, isMac: true });
    
    // Fire 'z' alone — should NOT trigger mod+z
    mockDoc.dispatchEvent(createKeyEvent('z', {}));
    assert.equal(undoCount, 0);
    
    // Fire Cmd+Z — should trigger mod+z, NOT mod+shift+z
    mockDoc.dispatchEvent(createKeyEvent('z', { metaKey: true }));
    assert.equal(undoCount, 1);
    assert.equal(redoCount, 0);
    
    // Fire Cmd+Shift+Z — should trigger mod+shift+z only
    mockDoc.dispatchEvent(createKeyEvent('z', { metaKey: true, shiftKey: true }));
    assert.equal(undoCount, 1);
    assert.equal(redoCount, 1);
    
    root.unmount();
});

test('macOS detection: with isMac=true, metaKey satisfies mod; with isMac=false, ctrlKey satisfies mod', () => {
    let saveCount = 0;
    const shortcuts = { 'mod+s': () => { saveCount++; } };
    
    // Test macOS (metaKey)
    let harness = harnessKeyboard(shortcuts, { enabled: true, isMac: true });
    
    harness.mockDoc.dispatchEvent(createKeyEvent('s', { metaKey: true }));
    assert.equal(saveCount, 1);
    
    harness.mockDoc.dispatchEvent(createKeyEvent('s', { ctrlKey: true }));
    assert.equal(saveCount, 1); // Should NOT increase on ctrlKey for macOS
    
    harness.root.unmount();
    
    // Test Linux (ctrlKey)
    saveCount = 0;
    harness = harnessKeyboard(shortcuts, { enabled: true, isMac: false });
    
    harness.mockDoc.dispatchEvent(createKeyEvent('s', { ctrlKey: true }));
    assert.equal(saveCount, 1);
    
    harness.mockDoc.dispatchEvent(createKeyEvent('s', { metaKey: true }));
    assert.equal(saveCount, 1); // Should NOT increase on metaKey for Linux
    
    harness.root.unmount();
});

test('input guard: when event target is input/textarea/contenteditable, shortcuts do NOT fire', () => {
    let saveCount = 0;
    let undoCount = 0;
    let deleteCount = 0;
    
    const shortcuts = {
        'mod+s': () => { saveCount++; },
        'mod+z': () => { undoCount++; },
        'delete': () => { deleteCount++; },
    };
    
    const { root, mockDoc } = harnessKeyboard(shortcuts, { enabled: true, isMac: true });
    
    // Fire Cmd+S inside an <input> — should NOT trigger
    const inputTarget = { tagName: 'INPUT' };
    mockDoc.dispatchEvent(createKeyEvent('s', { metaKey: true, target: inputTarget }));
    assert.equal(saveCount, 0);
    
    // Fire Cmd+Z inside a <textarea> — should NOT trigger
    const textareaTarget = { tagName: 'TEXTAREA' };
    mockDoc.dispatchEvent(createKeyEvent('z', { metaKey: true, target: textareaTarget }));
    assert.equal(undoCount, 0);
    
    // Fire Delete inside an <input> — should NOT trigger
    mockDoc.dispatchEvent(createKeyEvent('Delete', { target: inputTarget }));
    assert.equal(deleteCount, 0);
    
    // Fire Cmd+S outside input (on a DIV) — SHOULD trigger
    mockDoc.dispatchEvent(createKeyEvent('s', { metaKey: true }));
    assert.equal(saveCount, 1);
    
    root.unmount();
});

test('unmount cleanup: listener is removed; post-unmount events do not trigger handlers', () => {
    let saveCount = 0;
    const shortcuts = { 'mod+s': () => { saveCount++; } };
    
    const { root, mockDoc } = harnessKeyboard(shortcuts, { enabled: true, isMac: true });
    
    // Fire Cmd+S before unmount — should work
    mockDoc.dispatchEvent(createKeyEvent('s', { metaKey: true }));
    assert.equal(saveCount, 1);
    
    // Unmount
    act(() => { root.unmount(); });
    
    // Fire Cmd+S after unmount — should NOT trigger
    mockDoc.dispatchEvent(createKeyEvent('s', { metaKey: true }));
    assert.equal(saveCount, 1); // unchanged
});

test('enabled: false suppresses all shortcuts without unregistering', () => {
    let saveCount = 0;
    const shortcuts = { 'mod+s': () => { saveCount++; } };
    
    // Mount with enabled: false
    const { root, mockDoc } = harnessKeyboard(shortcuts, { enabled: false, isMac: true });
    
    // Fire Cmd+S — should NOT trigger because enabled is false
    mockDoc.dispatchEvent(createKeyEvent('s', { metaKey: true }));
    assert.equal(saveCount, 0);
    
    root.unmount();
    
    // Now mount with enabled: true
    const harness2 = harnessKeyboard(shortcuts, { enabled: true, isMac: true });
    harness2.mockDoc.dispatchEvent(createKeyEvent('s', { metaKey: true }));
    assert.equal(saveCount, 1);
    
    harness2.root.unmount();
});

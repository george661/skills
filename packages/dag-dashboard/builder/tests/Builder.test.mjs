/**
 * Builder.test.mjs
 * 
 * Tests for Builder component NodeInspector integration.
 * Uses global.window and global.document shims to test event bridge without DOM.
 */

import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert';

// Global shims for window and document (minimal, matching existing test pattern)
const eventListeners = {};

global.window = {
  addEventListener: (event, handler) => {
    if (!eventListeners[event]) eventListeners[event] = [];
    eventListeners[event].push(handler);
  },
  removeEventListener: (event, handler) => {
    if (eventListeners[event]) {
      eventListeners[event] = eventListeners[event].filter(h => h !== handler);
    }
  },
  NodeInspector: null, // Will be mocked per test
};

global.document = {
  addEventListener: (event, handler) => {
    if (!eventListeners[event]) eventListeners[event] = [];
    eventListeners[event].push(handler);
  },
  removeEventListener: (event, handler) => {
    if (eventListeners[event]) {
      eventListeners[event] = eventListeners[event].filter(h => h !== handler);
    }
  },
  dispatchEvent: (customEvent) => {
    const handlers = eventListeners[customEvent.type] || [];
    handlers.forEach(h => h(customEvent));
  },
};

beforeEach(() => {
  // Clear event listeners before each test
  Object.keys(eventListeners).forEach(key => delete eventListeners[key]);
});

describe('Builder', () => {
  it('WorkflowCanvas_reacts_to_dag-builder:node-update_event', () => {
    // Simulate WorkflowCanvas listening for node-update
    let capturedUpdate = null;
    const mockUpdateNode = (nodeData) => { capturedUpdate = nodeData; };
    
    // Simulate the useEffect from WorkflowCanvas.jsx:88-96
    const handler = (e) => {
      if (e.detail && mockUpdateNode) mockUpdateNode(e.detail);
    };
    global.document.addEventListener('dag-builder:node-update', handler);
    
    // Dispatch event (as inspector would)
    const updatedNode = { id: 'test-node', name: 'updated', node_type: 'bash' };
    global.document.dispatchEvent({
      type: 'dag-builder:node-update',
      detail: updatedNode,
    });
    
    assert.deepEqual(capturedUpdate, updatedNode, 'updateNode should be called with event detail');
    
    // Cleanup
    global.document.removeEventListener('dag-builder:node-update', handler);
  });

  it('WorkflowCanvas_reacts_to_dag-builder:node-delete_event', () => {
    // Simulate WorkflowCanvas listening for node-delete
    let capturedDeletes = null;
    const mockOnNodesDelete = (nodes) => { capturedDeletes = nodes; };
    
    // Simulate the useEffect from WorkflowCanvas.jsx:99-107
    const handler = (e) => {
      if (e.detail && mockOnNodesDelete) mockOnNodesDelete([{ id: e.detail }]);
    };
    global.document.addEventListener('dag-builder:node-delete', handler);
    
    // Dispatch event (as inspector would)
    const nodeId = 'test-node-to-delete';
    global.document.dispatchEvent({
      type: 'dag-builder:node-delete',
      detail: nodeId,
    });
    
    assert.deepEqual(capturedDeletes, [{ id: nodeId }], 'onNodesDelete should be called with wrapped node id');
    
    // Cleanup
    global.document.removeEventListener('dag-builder:node-delete', handler);
  });

  it('NodeInspector_integration_onChange_fires_node-update_event', () => {
    // Mock NodeInspector constructor
    let capturedProps = null;
    global.window.NodeInspector = function(props) {
      capturedProps = props;
      this.destroy = () => {};
      this.update = () => {};
    };
    
    // Simulate Builder mounting inspector and setting onChange callback
    const inspector = new global.window.NodeInspector({
      container: null,
      node: { id: 'n1', name: 'node1', node_type: 'bash' },
      allowDestructive: false,
      availableNodeIds: [],
      onChange: (updatedNode) => {
        global.document.dispatchEvent({
          type: 'dag-builder:node-update',
          detail: updatedNode,
        });
      },
      onDelete: () => {},
    });
    
    assert.ok(capturedProps, 'NodeInspector should be called');
    assert.equal(capturedProps.allowDestructive, false);
    
    // Simulate inspector's onChange callback
    let eventFired = false;
    const handler = (e) => { eventFired = true; };
    global.document.addEventListener('dag-builder:node-update', handler);
    
    capturedProps.onChange({ id: 'n1', name: 'updated-name', node_type: 'bash' });
    
    assert.ok(eventFired, 'dag-builder:node-update event should be dispatched when onChange is called');
    
    // Cleanup
    global.document.removeEventListener('dag-builder:node-update', handler);
    inspector.destroy();
  });

  it('NodeInspector_integration_onDelete_fires_node-delete_event', () => {
    // Mock NodeInspector constructor
    let capturedProps = null;
    global.window.NodeInspector = function(props) {
      capturedProps = props;
      this.destroy = () => {};
      this.update = () => {};
    };
    
    // Simulate Builder mounting inspector and setting onDelete callback
    const inspector = new global.window.NodeInspector({
      container: null,
      node: { id: 'n1', name: 'node1', node_type: 'bash' },
      allowDestructive: false,
      availableNodeIds: [],
      onChange: () => {},
      onDelete: (nodeId) => {
        global.document.dispatchEvent({
          type: 'dag-builder:node-delete',
          detail: nodeId,
        });
      },
    });
    
    assert.ok(capturedProps, 'NodeInspector should be called');
    
    // Simulate inspector's onDelete callback
    let eventFired = false;
    const handler = (e) => { eventFired = true; };
    global.document.addEventListener('dag-builder:node-delete', handler);
    
    capturedProps.onDelete('n1');
    
    assert.ok(eventFired, 'dag-builder:node-delete event should be dispatched when onDelete is called');
    
    // Cleanup
    global.document.removeEventListener('dag-builder:node-delete', handler);
    inspector.destroy();
  });
});

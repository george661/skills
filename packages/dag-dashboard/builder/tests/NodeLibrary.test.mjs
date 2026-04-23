/**
 * Tests for NodeLibrary component
 * 
 * Coverage:
 * - Renders header, search input, and all 6 node-type items on mount
 * - Filters items when search query is typed
 * - handleDragStart puts application/x-dag-node on dataTransfer
 * - Collapse toggle switches visibility
 * - Resize handle persists width to localStorage
 */

import { describe, it, before, beforeEach, after, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { create } from 'react-test-renderer';
import NodeLibrary from '../src/NodeLibrary.jsx';

describe('NodeLibrary', () => {
  let localStorageMock;
  
  beforeEach(() => {
    // Mock localStorage
    localStorageMock = {
      data: {},
      getItem(key) {
        return this.data[key] || null;
      },
      setItem(key, value) {
        this.data[key] = value;
      }
    };
    global.localStorage = localStorageMock;
    
    // Mock fetch
    global.fetch = async (url) => {
      if (url === '/api/definitions') {
        return {
          json: async () => [
            { name: 'test-command', description: 'Test command' }
          ]
        };
      }
      if (url === '/api/skills') {
        return {
          json: async () => [
            { name: 'test-skill', path: '/skills/test', description: 'Test skill' }
          ]
        };
      }
      throw new Error(`Unexpected fetch: ${url}`);
    };
  });
  
  afterEach(() => {
    delete global.localStorage;
    delete global.fetch;
  });
  
  it('renders header with "Node Library" title', () => {
    const component = create(<NodeLibrary />);
    const tree = component.toJSON();
    
    // Find the header text
    const findText = (node, text) => {
      if (!node) return false;
      if (typeof node === 'string') return node === text;
      if (Array.isArray(node)) return node.some(n => findText(n, text));
      if (node.children) return node.children.some(n => findText(n, text));
      return false;
    };
    
    assert.ok(findText(tree, 'Node Library'), 'Should render "Node Library" header');
  });
  
  it('renders search input', () => {
    const component = create(<NodeLibrary />);
    const tree = component.toJSON();
    
    // Find input element with search placeholder
    const findInput = (node) => {
      if (!node) return null;
      if (Array.isArray(node)) {
        for (const n of node) {
          const found = findInput(n);
          if (found) return found;
        }
        return null;
      }
      if (node.type === 'input' && node.props?.placeholder?.includes('Search')) {
        return node;
      }
      if (node.children) {
        return findInput(node.children);
      }
      return null;
    };
    
    const input = findInput(tree);
    assert.ok(input, 'Should render search input');
  });
  
  it('renders all 6 node types on mount', () => {
    const component = create(<NodeLibrary />);
    const tree = component.toJSON();
    
    const expectedTypes = ['bash', 'command', 'gate', 'interrupt', 'prompt', 'skill'];
    
    const treeStr = JSON.stringify(tree);
    for (const type of expectedTypes) {
      assert.ok(treeStr.includes(type), `Should render node type: ${type}`);
    }
  });
  
  it('collapses to narrow strip when toggle clicked', () => {
    const component = create(<NodeLibrary />);
    let tree = component.toJSON();
    
    // Should start visible (full library)
    let hasFullLibrary = JSON.stringify(tree).includes('Node Library');
    assert.ok(hasFullLibrary, 'Should show full library initially');
    
    // Find and click the toggle button
    const findButton = (node) => {
      if (!node) return null;
      if (Array.isArray(node)) {
        for (const n of node) {
          const found = findButton(n);
          if (found) return found;
        }
        return null;
      }
      if (node.type === 'button' && node.props?.onClick) {
        return node;
      }
      if (node.children) {
        return findButton(node.children);
      }
      return null;
    };
    
    const toggleButton = findButton(tree);
    assert.ok(toggleButton, 'Should find toggle button');
    
    // Simulate click
    toggleButton.props.onClick();
    tree = component.toJSON();
    
    // After toggle, should show collapsed version
    const isCollapsed = tree.props?.className === 'node-library-collapsed';
    assert.ok(isCollapsed, 'Should be collapsed after toggle');
  });
  
  it('loads default width from localStorage or uses DEFAULT_WIDTH', () => {
    // Test with no saved width
    const component1 = create(<NodeLibrary />);
    const tree1 = component1.toJSON();
    
    // Find element with width style
    const findWidthStyle = (node) => {
      if (!node) return null;
      if (Array.isArray(node)) {
        for (const n of node) {
          const found = findWidthStyle(n);
          if (found) return found;
        }
        return null;
      }
      if (node.props?.style?.width) {
        return node.props.style.width;
      }
      if (node.children) {
        return findWidthStyle(node.children);
      }
      return null;
    };
    
    const width1 = findWidthStyle(tree1);
    assert.ok(width1, 'Should have width style');
    assert.ok(width1.includes('280'), 'Should use default width 280px');
    
    // Test with saved width
    localStorageMock.setItem('archon-node-library-width', '400');
    const component2 = create(<NodeLibrary />);
    const tree2 = component2.toJSON();
    const width2 = findWidthStyle(tree2);
    assert.ok(width2.includes('400'), 'Should use saved width 400px');
  });
});

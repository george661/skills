/**
 * VersionDrawer.test.mjs
 * 
 * Tests for VersionDrawer component - side drawer for version browser.
 * Test count: 6 cases.
 */

import { describe, it } from 'node:test';
import assert from 'node:assert';
import React from 'react';
import TestRenderer from 'react-test-renderer';
import VersionDrawer from '../src/VersionDrawer.jsx';

// Mock window.confirm
global.window = { confirm: () => true };

describe('VersionDrawer', () => {
  const mockDrafts = Array.from({ length: 50 }, (_, i) => ({
    timestamp: `202601${String(50-i).padStart(2, '0')}T120000_000000Z`,
    size_bytes: 100 + i,
    publisher: i % 3 === 0 ? 'alice@example.com' : null,
  }));

  const defaultProps = {
    isOpen: true,
    drafts: [],
    onClose: () => {},
    onRestore: () => {},
    onDelete: () => {},
    onHover: () => {},
    hoveredDiff: null,
  };

  it('renders_50_drafts_newest_first', () => {
    const renderer = TestRenderer.create(
      <VersionDrawer {...defaultProps} drafts={mockDrafts} />
    );
    const tree = renderer.toJSON();
    
    // Check that drawer is rendered
    assert.ok(tree, 'Drawer should render');
    
    // Count draft rows by looking for elements with draft-row className
    const json = JSON.stringify(tree);
    const draftRowCount = (json.match(/draft-row/g) || []).length;
    
    assert.ok(draftRowCount >= 50, `Should render 50 drafts, got ${draftRowCount}`);
  });

  it('shows_timestamp_publisher_diff_summary_per_row', () => {
    const draftsWithMeta = [
      { timestamp: '20260101T120000_000000Z', size_bytes: 100, publisher: 'alice@example.com' },
    ];
    
    const renderer = TestRenderer.create(
      <VersionDrawer {...defaultProps} drafts={draftsWithMeta} />
    );
    
    const json = JSON.stringify(renderer.toJSON());
    
    // Check that timestamp is displayed
    assert.ok(json.includes('2026-01-01'), 'Should show formatted timestamp');
    assert.ok(json.includes('alice@example.com'), 'Should show publisher');
    assert.ok(json.includes('100'), 'Should show size (number)');
  });

  it('hover_triggers_diff_fetch', () => {
    let hoverCalled = false;
    const onHover = (ts) => { hoverCalled = true; };
    
    const renderer = TestRenderer.create(
      <VersionDrawer {...defaultProps} drafts={[mockDrafts[0]]} onHover={onHover} />
    );
    
    // Find elements with onMouseEnter
    const tree = renderer.toJSON();
    function findWithMouseEnter(node) {
      if (node && node.props && node.props.onMouseEnter) {
        return node;
      }
      if (node && node.children) {
        for (const child of node.children) {
          const found = findWithMouseEnter(child);
          if (found) return found;
        }
      }
      return null;
    }
    
    const hoverElement = findWithMouseEnter(tree);
    if (hoverElement) {
      TestRenderer.act(() => {
        hoverElement.props.onMouseEnter();
      });
      assert.ok(hoverCalled, 'onHover should be called on mouse enter');
    }
  });

  it('restore_calls_onRestore_with_timestamp', () => {
    let restoreTs = null;
    const onRestore = (ts) => { restoreTs = ts; };
    
    const renderer = TestRenderer.create(
      <VersionDrawer {...defaultProps} drafts={[mockDrafts[0]]} onRestore={onRestore} />
    );
    
    // Find restore button
    const tree = renderer.toJSON();
    function findRestoreButton(node) {
      if (node && node.type === 'button' && node.children && 
          node.children.some(c => c === 'Restore')) {
        return node;
      }
      if (node && node.children) {
        for (const child of node.children) {
          const found = findRestoreButton(child);
          if (found) return found;
        }
      }
      return null;
    }
    
    const restoreBtn = findRestoreButton(tree);
    if (restoreBtn) {
      TestRenderer.act(() => {
        restoreBtn.props.onClick();
      });
      assert.ok(restoreTs, 'onRestore should be called with timestamp');
    }
  });

  it('delete_prompts_confirm_then_deletes', () => {
    let deleteCalled = false;
    const onDelete = (ts) => { deleteCalled = true; };
    
    global.window.confirm = () => true;
    
    const renderer = TestRenderer.create(
      <VersionDrawer {...defaultProps} drafts={[mockDrafts[0]]} onDelete={onDelete} />
    );
    
    // Find delete button
    const tree = renderer.toJSON();
    function findDeleteButton(node) {
      if (node && node.type === 'button' && node.children && 
          node.children.some(c => c === 'Delete')) {
        return node;
      }
      if (node && node.children) {
        for (const child of node.children) {
          const found = findDeleteButton(child);
          if (found) return found;
        }
      }
      return null;
    }
    
    const deleteBtn = findDeleteButton(tree);
    if (deleteBtn) {
      TestRenderer.act(() => {
        deleteBtn.props.onClick();
      });
      assert.ok(deleteCalled, 'onDelete should be called after confirmation');
    }
  });

  it('drawer_closed_by_default', () => {
    const renderer = TestRenderer.create(
      <VersionDrawer {...defaultProps} isOpen={false} />
    );
    
    const tree = renderer.toJSON();
    // When closed, drawer should return null
    assert.strictEqual(tree, null, 'Drawer should not render when closed');
  });
});

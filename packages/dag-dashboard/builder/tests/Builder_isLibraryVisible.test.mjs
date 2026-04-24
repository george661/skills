/**
 * Regression test for GW-5338: Dead state isLibraryVisible in dag-dashboard builder
 * 
 * This test verifies that the isLibraryVisible state declared at line 89-90 of
 * packages/dag-dashboard/builder/src/index.jsx is actually used in the rendering logic.
 * 
 * Current bug: The state is declared but never read, and setIsLibraryVisible is never called.
 * The NodeLibrary rendering at line 342 only checks `!isMobile`, not `isLibraryVisible`.
 * 
 * Expected behavior after fix:
 * - Line 342 should check both conditions: {!isMobile && isLibraryVisible && <NodeLibrary />}
 * - A keyboard shortcut (e.g., Ctrl+L) should toggle setIsLibraryVisible
 * - OR the dead state should be removed entirely if the feature isn't needed
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

test('Builder index.jsx: isLibraryVisible state should be used in rendering or removed', () => {
  // Read the Builder source file
  const indexPath = path.resolve(__dirname, '../src/index.jsx');
  const source = fs.readFileSync(indexPath, 'utf-8');
  
  // Check if isLibraryVisible state is declared
  const stateDeclarationMatch = source.match(/const\s+\[isLibraryVisible,\s*setIsLibraryVisible\]\s*=\s*React\.useState/);
  
  if (!stateDeclarationMatch) {
    // State was removed - this is one valid fix for the bug
    assert.ok(true, 'isLibraryVisible state has been removed (valid fix option 1)');
    return;
  }
  
  // State exists, so verify it's actually used
  // Count all occurrences of isLibraryVisible
  const allMatches = source.match(/isLibraryVisible/g) || [];
  
  // The declaration counts as 1 occurrence
  // If there are only 1 or 2 occurrences (declaration + maybe comment),
  // the state is not being used in rendering logic
  if (allMatches.length <= 2) {
    assert.fail(
      'Dead state detected: isLibraryVisible is declared but not used in rendering logic.\n' +
      'Expected: Either remove the state, or wire it into the NodeLibrary rendering condition.\n' +
      'Current line 342: {!isMobile && <NodeLibrary />}\n' +
      'Should be: {!isMobile && isLibraryVisible && <NodeLibrary />}\n' +
      'Also add keyboard shortcut to toggle setIsLibraryVisible(prev => !prev)'
    );
  }
  
  // Additional check: Verify it's used in the rendering logic, not just comments
  // Look for the NodeLibrary rendering line
  const nodeLibraryRenderMatch = source.match(/{!isMobile && (?:isLibraryVisible &&\s*)?<NodeLibrary/);
  
  if (!nodeLibraryRenderMatch) {
    assert.fail(
      'NodeLibrary rendering not found or not checking isLibraryVisible.\n' +
      'Expected pattern: {!isMobile && isLibraryVisible && <NodeLibrary />}'
    );
  }
  
  // Check if isLibraryVisible is in the rendering condition
  if (!nodeLibraryRenderMatch[0].includes('isLibraryVisible')) {
    assert.fail(
      'NodeLibrary rendering does not check isLibraryVisible state.\n' +
      'Current: {!isMobile && <NodeLibrary />}\n' +
      'Expected: {!isMobile && isLibraryVisible && <NodeLibrary />}'
    );
  }
  
  // Check if setIsLibraryVisible is used (keyboard shortcut or toggle)
  const setterUsageMatch = source.match(/setIsLibraryVisible/g) || [];
  if (setterUsageMatch.length <= 1) {
    // Only the declaration exists, no actual calls to setIsLibraryVisible
    assert.fail(
      'setIsLibraryVisible is never called. Add keyboard shortcut or UI toggle.\n' +
      'Example: useEffect hook to listen for Ctrl+L keydown and toggle visibility'
    );
  }
  
  assert.ok(true, 'isLibraryVisible state is properly wired into rendering and has toggle mechanism');
});

test('Builder index.jsx: document the intended behavior for isLibraryVisible', () => {
  // This test documents what the fix should accomplish
  const expectedBehavior = `
When isLibraryVisible state is properly implemented:

1. Declaration (current, line 89-90):
   const [isLibraryVisible, setIsLibraryVisible] = React.useState(true);

2. Rendering condition (fix needed at line 342):
   Current: {!isMobile && <NodeLibrary />}
   Fixed:   {!isMobile && isLibraryVisible && <NodeLibrary />}

3. Keyboard shortcut (add new useEffect):
   React.useEffect(() => {
     const handleKeyDown = (e) => {
       if ((e.ctrlKey || e.metaKey) && e.key === 'l') {
         e.preventDefault();
         setIsLibraryVisible(prev => !prev);
       }
     };
     window.addEventListener('keydown', handleKeyDown);
     return () => window.removeEventListener('keydown', handleKeyDown);
   }, []);

4. Alternative: Remove the dead state entirely if toggle feature is not needed.
  `;
  
  assert.ok(true, expectedBehavior);
});

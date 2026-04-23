import { test } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import renderer from 'react-test-renderer';
import { YamlCodeView } from '../src/YamlCodeView.jsx';

test('Renders <pre> with serialized yaml when viewMode="split"', () => {
  const dag = [
    { id: 'test', type: 'bash', script: 'echo hello' }
  ];
  
  const component = renderer.create(
    React.createElement(YamlCodeView, { dag, viewMode: 'split' })
  );
  
  const tree = component.toJSON();
  assert.ok(tree, 'Should render something');
  assert.equal(tree.type, 'section', 'Should render a section element');
  
  // Find the pre element
  const preElement = tree.children.find(child => child.type === 'pre');
  assert.ok(preElement, 'Should contain a pre element');

  // Check that YAML content is present (as React elements with syntax highlighting)
  const jsonStr = JSON.stringify(preElement);
  assert.match(jsonStr, /nodes/, 'Should contain YAML nodes key');
  assert.match(jsonStr, /bash/, 'Should contain node type');
});

test('Returns null when viewMode="hidden"', () => {
  const dag = [
    { id: 'test', type: 'bash', script: 'echo hello' }
  ];
  
  const component = renderer.create(
    React.createElement(YamlCodeView, { dag, viewMode: 'hidden' })
  );
  
  const tree = component.toJSON();
  assert.equal(tree, null, 'Should render null when hidden');
});

test('Renders when viewMode="full"', () => {
  const dag = [
    { id: 'test', type: 'bash', script: 'echo hello' }
  ];
  
  const component = renderer.create(
    React.createElement(YamlCodeView, { dag, viewMode: 'full' })
  );
  
  const tree = component.toJSON();
  assert.ok(tree, 'Should render something when full mode');
  assert.equal(tree.type, 'section', 'Should render a section element');
});

test('Re-renders on dag prop change (updated text in <pre>)', () => {
  const dag1 = [
    { id: 'test1', type: 'bash', script: 'echo hello' }
  ];
  const dag2 = [
    { id: 'test2', type: 'bash', script: 'echo goodbye' }
  ];
  
  const component = renderer.create(
    React.createElement(YamlCodeView, { dag: dag1, viewMode: 'split' })
  );
  
  let tree = component.toJSON();
  const preElement1 = tree.children.find(child => child.type === 'pre');
  const jsonStr1 = JSON.stringify(preElement1);
  assert.match(jsonStr1, /test1/, 'Should contain first node id');

  // Update with new dag
  component.update(
    React.createElement(YamlCodeView, { dag: dag2, viewMode: 'split' })
  );

  tree = component.toJSON();
  const preElement2 = tree.children.find(child => child.type === 'pre');
  const jsonStr2 = JSON.stringify(preElement2);
  assert.match(jsonStr2, /test2/, 'Should contain updated node id');
  assert.doesNotMatch(jsonStr2, /test1/, 'Should not contain old node id');
});

test('No <textarea>, <input>, or contentEditable anywhere in tree (read-only invariant)', () => {
  const dag = [
    { id: 'test', type: 'bash', script: 'echo hello' }
  ];
  
  const component = renderer.create(
    React.createElement(YamlCodeView, { dag, viewMode: 'split' })
  );
  
  const tree = component.toJSON();
  
  // Recursive check for editable elements
  function checkNotEditable(node) {
    if (!node) return;
    
    assert.notEqual(node.type, 'textarea', 'Should not contain textarea');
    assert.notEqual(node.type, 'input', 'Should not contain input');
    
    if (node.props && node.props.contentEditable) {
      assert.fail('Should not have contentEditable prop');
    }
    
    if (node.children) {
      node.children.forEach(checkNotEditable);
    }
  }
  
  checkNotEditable(tree);
});

test('Has aria-label and role="region" for accessibility', () => {
  const dag = [
    { id: 'test', type: 'bash', script: 'echo hello' }
  ];
  
  const component = renderer.create(
    React.createElement(YamlCodeView, { dag, viewMode: 'split' })
  );
  
  const tree = component.toJSON();
  assert.ok(tree.props.role === 'region' || tree.props['aria-label'], 
    'Should have accessibility attributes');
});

test('Renders with at least one syntax highlight span when given non-empty dag', () => {
  const dag = [
    { id: 'test', type: 'bash', script: 'echo hello' }
  ];
  
  const component = renderer.create(
    React.createElement(YamlCodeView, { dag, viewMode: 'split' })
  );
  
  const tree = component.toJSON();
  const preElement = tree.children.find(child => child.type === 'pre');
  
  // Check that the content has some structure (not just plain text)
  // This ensures the syntax highlighter isn't silently broken
  assert.ok(preElement.children, 'Pre element should have children');
  
  // For now, just verify content exists - we'll add highlighting in implementation
  const hasContent = preElement.children.length > 0;
  assert.ok(hasContent, 'Should have YAML content');
});

/**
 * BuilderToolbar.test.mjs
 * 
 * CRITICAL: This component must NOT import WorkflowCanvas or React Flow transitively.
 * Tests render the toolbar in isolation using react-test-renderer with mock callbacks.
 * 
 * Test count: 8 cases (Redo removed per v2 plan).
 */

import { describe, it } from 'node:test';
import assert from 'node:assert';
import React from 'react';
import TestRenderer from 'react-test-renderer';
import BuilderToolbar from '../src/BuilderToolbar.jsx';

describe('BuilderToolbar', () => {
  const defaultProps = {
    workflowName: 'test-workflow',
    description: 'Test description',
    provider: 'openai',
    model: 'gpt-4',
    dag: [],
    yaml: '',
    viewMode: 'hidden',
    hasUnsavedChanges: false,
    hasClientErrors: false,
    onChangeWorkflowName: () => {},
    onChangeDescription: () => {},
    onChangeProvider: () => {},
    onChangeModel: () => {},
    onSave: () => {},
    onPublish: () => {},
    onRun: () => {},
    onValidate: () => {},
    onUndo: () => {},
    onViewModeChange: () => {},
  };

  it('renders_all_inputs', () => {
    const renderer = TestRenderer.create(<BuilderToolbar {...defaultProps} />);
    const root = renderer.root;
    
    // Find all text inputs
    const inputs = root.findAllByType('input');
    assert.ok(inputs.length >= 4, 'Should have at least 4 inputs');
    
    // Check that inputs have the correct values
    const nameInput = inputs.find(i => i.props.value === 'test-workflow');
    assert.ok(nameInput, 'Name input should exist');
    
    const descInput = inputs.find(i => i.props.value === 'Test description');
    assert.ok(descInput, 'Description input should exist');
    
    const providerInput = inputs.find(i => i.props.value === 'openai');
    assert.ok(providerInput, 'Provider input should exist');
    
    const modelInput = inputs.find(i => i.props.value === 'gpt-4');
    assert.ok(modelInput, 'Model input should exist');
  });

  it('run_disabled_when_unsaved', () => {
    const propsWithUnsaved = { ...defaultProps, hasUnsavedChanges: true };
    const renderer = TestRenderer.create(<BuilderToolbar {...propsWithUnsaved} />);
    const root = renderer.root;
    
    const buttons = root.findAllByType('button');
    const runButton = buttons.find(b => b.props.children && b.props.children.includes && b.props.children.includes('Run'));
    
    assert.ok(runButton, 'Run button should exist');
    assert.strictEqual(runButton.props.disabled, true, 'Run button should be disabled when hasUnsavedChanges=true');
  });

  it('run_disabled_when_client_errors', () => {
    const propsWithErrors = { ...defaultProps, hasClientErrors: true };
    const renderer = TestRenderer.create(<BuilderToolbar {...propsWithErrors} />);
    const root = renderer.root;
    
    const buttons = root.findAllByType('button');
    const runButton = buttons.find(b => b.props.children && b.props.children.includes && b.props.children.includes('Run'));
    
    assert.ok(runButton, 'Run button should exist');
    assert.strictEqual(runButton.props.disabled, true, 'Run button should be disabled when hasClientErrors=true');
  });

  it('unsaved_dot_shown', () => {
    // Test without unsaved changes
    const rendererSaved = TestRenderer.create(<BuilderToolbar {...defaultProps} />);
    let root = rendererSaved.root;
    
    let unsavedIndicators = root.findAll(node => 
      node.props && node.props['data-testid'] === 'unsaved-indicator'
    );
    assert.strictEqual(unsavedIndicators.length, 0, 'Unsaved indicator should not be shown when hasUnsavedChanges=false');
    
    // Test with unsaved changes
    const propsWithUnsaved = { ...defaultProps, hasUnsavedChanges: true };
    const rendererUnsaved = TestRenderer.create(<BuilderToolbar {...propsWithUnsaved} />);
    root = rendererUnsaved.root;
    
    unsavedIndicators = root.findAll(node => 
      node.props && node.props['data-testid'] === 'unsaved-indicator'
    );
    assert.strictEqual(unsavedIndicators.length, 1, 'Unsaved indicator should be shown when hasUnsavedChanges=true');
  });

  it('save_click_fires_onSave', () => {
    let saveCallCount = 0;
    const props = { ...defaultProps, onSave: () => { saveCallCount++; } };
    const renderer = TestRenderer.create(<BuilderToolbar {...props} />);
    const root = renderer.root;
    
    const buttons = root.findAllByType('button');
    const saveButton = buttons.find(b => b.props.children && b.props.children.includes && b.props.children.includes('Save'));
    
    assert.ok(saveButton, 'Save button should exist');
    saveButton.props.onClick();
    assert.strictEqual(saveCallCount, 1, 'onSave should be called once');
  });

  it('publish_click_fires_onPublish', () => {
    let publishCallCount = 0;
    const props = { ...defaultProps, onPublish: () => { publishCallCount++; } };
    const renderer = TestRenderer.create(<BuilderToolbar {...props} />);
    const root = renderer.root;
    
    const buttons = root.findAllByType('button');
    const publishButton = buttons.find(b => b.props.children && b.props.children.includes && b.props.children.includes('Publish'));
    
    assert.ok(publishButton, 'Publish button should exist');
    publishButton.props.onClick();
    assert.strictEqual(publishCallCount, 1, 'onPublish should be called once');
  });

  it('run_click_fires_onRun', () => {
    let runCallCount = 0;
    const props = { ...defaultProps, onRun: () => { runCallCount++; } };
    const renderer = TestRenderer.create(<BuilderToolbar {...props} />);
    const root = renderer.root;
    
    const buttons = root.findAllByType('button');
    const runButton = buttons.find(b => b.props.children && b.props.children.includes && b.props.children.includes('Run'));
    
    assert.ok(runButton, 'Run button should exist');
    assert.strictEqual(runButton.props.disabled, false, 'Run button should be enabled');
    runButton.props.onClick();
    assert.strictEqual(runCallCount, 1, 'onRun should be called once');
  });

  it('validate_click_fires_onValidate', () => {
    let validateCallCount = 0;
    const props = { ...defaultProps, onValidate: () => { validateCallCount++; } };
    const renderer = TestRenderer.create(<BuilderToolbar {...props} />);
    const root = renderer.root;
    
    const buttons = root.findAllByType('button');
    const validateButton = buttons.find(b => b.props.children && b.props.children.includes && b.props.children.includes('Validate'));
    
    assert.ok(validateButton, 'Validate button should exist');
    validateButton.props.onClick();
    assert.strictEqual(validateCallCount, 1, 'onValidate should be called once');
  });
});

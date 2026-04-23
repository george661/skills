/**
 * BuilderToolbar.jsx
 * 
 * Top toolbar for the Builder UI.
 * Contains 4 inputs (name, description, provider, model),
 * 5 action buttons (Save, Publish, Run, Validate, Undo),
 * and view-mode toggle (hidden/split/full).
 * 
 * CRITICAL: Does NOT import WorkflowCanvas or React Flow.
 */

import React from 'react';

export default function BuilderToolbar({
  workflowName,
  description,
  provider,
  model,
  dag,
  yaml,
  viewMode,
  hasUnsavedChanges,
  hasClientErrors,
  onChangeWorkflowName,
  onChangeDescription,
  onChangeProvider,
  onChangeModel,
  onSave,
  onPublish,
  onRun,
  onValidate,
  onUndo,
  onViewModeChange,
}) {
  // Run button is disabled when there are unsaved changes OR client errors
  const isRunDisabled = hasUnsavedChanges || hasClientErrors;

  return (
    <div className="builder-toolbar" style={{ 
      display: 'flex', 
      flexDirection: 'column',
      gap: '8px',
      padding: '12px',
      borderBottom: '1px solid #ddd',
      backgroundColor: '#f9f9f9'
    }}>
      {/* Metadata inputs row */}
      <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <label style={{ fontSize: '12px', fontWeight: '500' }}>Name:</label>
          <input
            type="text"
            value={workflowName}
            onChange={(e) => onChangeWorkflowName(e.target.value)}
            style={{ padding: '4px 8px', fontSize: '14px', minWidth: '150px' }}
          />
          {hasUnsavedChanges && (
            <span 
              data-testid="unsaved-indicator"
              style={{ 
                display: 'inline-block',
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: '#ff6b00',
                marginLeft: '4px'
              }}
              title="Unsaved changes"
            />
          )}
        </div>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <label style={{ fontSize: '12px', fontWeight: '500' }}>Description:</label>
          <input
            type="text"
            value={description}
            onChange={(e) => onChangeDescription(e.target.value)}
            style={{ padding: '4px 8px', fontSize: '14px', minWidth: '200px' }}
          />
        </div>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <label style={{ fontSize: '12px', fontWeight: '500' }}>Provider:</label>
          <input
            type="text"
            value={provider}
            onChange={(e) => onChangeProvider(e.target.value)}
            style={{ padding: '4px 8px', fontSize: '14px', minWidth: '100px' }}
          />
        </div>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <label style={{ fontSize: '12px', fontWeight: '500' }}>Model:</label>
          <input
            type="text"
            value={model}
            onChange={(e) => onChangeModel(e.target.value)}
            style={{ padding: '4px 8px', fontSize: '14px', minWidth: '120px' }}
          />
        </div>
      </div>

      {/* Action buttons and view mode toggle row */}
      <div style={{ display: 'flex', gap: '8px', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button 
            onClick={onSave}
            style={{ padding: '6px 16px', fontSize: '14px', cursor: 'pointer' }}
          >
            Save
          </button>
          
          <button 
            onClick={onPublish}
            style={{ padding: '6px 16px', fontSize: '14px', cursor: 'pointer' }}
          >
            Publish
          </button>
          
          <button 
            onClick={onRun}
            disabled={isRunDisabled}
            style={{ 
              padding: '6px 16px', 
              fontSize: '14px', 
              cursor: isRunDisabled ? 'not-allowed' : 'pointer',
              opacity: isRunDisabled ? 0.5 : 1
            }}
          >
            Run
          </button>
          
          <button 
            onClick={onValidate}
            style={{ padding: '6px 16px', fontSize: '14px', cursor: 'pointer' }}
          >
            Validate
          </button>
          
          <button 
            onClick={onUndo}
            style={{ padding: '6px 16px', fontSize: '14px', cursor: 'pointer' }}
          >
            Undo
          </button>
        </div>

        {/* View mode toggle */}
        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
          <label style={{ fontSize: '12px', fontWeight: '500', marginRight: '4px' }}>YAML View:</label>
          <button
            onClick={() => onViewModeChange('hidden')}
            style={{
              padding: '4px 12px',
              fontSize: '12px',
              cursor: 'pointer',
              backgroundColor: viewMode === 'hidden' ? '#007bff' : '#fff',
              color: viewMode === 'hidden' ? '#fff' : '#000',
              border: '1px solid #ccc',
              borderRadius: '4px 0 0 4px'
            }}
          >
            Hidden
          </button>
          <button
            onClick={() => onViewModeChange('split')}
            style={{
              padding: '4px 12px',
              fontSize: '12px',
              cursor: 'pointer',
              backgroundColor: viewMode === 'split' ? '#007bff' : '#fff',
              color: viewMode === 'split' ? '#fff' : '#000',
              border: '1px solid #ccc',
              borderLeft: 'none',
              borderRight: 'none'
            }}
          >
            Split
          </button>
          <button
            onClick={() => onViewModeChange('full')}
            style={{
              padding: '4px 12px',
              fontSize: '12px',
              cursor: 'pointer',
              backgroundColor: viewMode === 'full' ? '#007bff' : '#fff',
              color: viewMode === 'full' ? '#fff' : '#000',
              border: '1px solid #ccc',
              borderRadius: '0 4px 4px 0'
            }}
          >
            Full
          </button>
        </div>
      </div>
    </div>
  );
}

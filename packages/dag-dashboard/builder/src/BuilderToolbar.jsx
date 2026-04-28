/**
 * BuilderToolbar.jsx
 *
 * Top toolbar for the Builder UI.
 * Contains 4 inputs (name, description, provider, model),
 * 5 action buttons (Save, Publish, Run, Validate, Undo),
 * and view-mode toggle (hidden/split/full).
 *
 * CRITICAL: Does NOT import WorkflowCanvas or React Flow.
 *
 * GW-5253: responsive mobile layout. When `isMobile` is true:
 *   - Metadata inputs (name/description/provider/model) collapse behind a disclosure.
 *   - Action buttons wrap and every button has min-height 44px for tappable targets.
 *   - YAML view-mode toggle is hidden (mobile always uses canvas-only view).
 */

import React from 'react';

const BUTTON_BASE_STYLE = {
  padding: '10px 16px',
  fontSize: '14px',
  minHeight: '44px',
  touchAction: 'manipulation',
};

const VIEW_MODE_BUTTON_BASE_STYLE = {
  padding: '10px 12px',
  fontSize: '12px',
  minHeight: '44px',
  cursor: 'pointer',
  touchAction: 'manipulation',
};

const INPUT_STYLE = {
  padding: '8px',
  // 16px prevents iOS auto-zoom on input focus (WCAG + Apple HIG).
  fontSize: '16px',
  minHeight: '44px',
  flex: '1 1 auto',
  minWidth: '0',
  boxSizing: 'border-box',
};

const FIELD_ROW_STYLE = {
  display: 'flex',
  alignItems: 'center',
  gap: '4px',
  flex: '1 1 auto',
  minWidth: 0,
};

export default function BuilderToolbar({
  workflowName,
  description,
  provider,
  model,
  viewMode,
  hasUnsavedChanges,
  hasClientErrors,
  hasPublishableDraft,
  triggerEnabled = false,
  isMobile = false,
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
  onOpenVersions,
}) {
  // Run button is disabled when there are unsaved changes, client errors, or the
  // server doesn't have /api/trigger mounted (DAG_DASHBOARD_TRIGGER_ENABLED=false).
  const isRunDisabled = hasUnsavedChanges || hasClientErrors || !triggerEnabled;
  const runDisabledReason = !triggerEnabled
    ? 'Trigger endpoint disabled — set DAG_DASHBOARD_TRIGGER_ENABLED=true to enable.'
    : hasClientErrors
    ? 'Fix validation errors before running.'
    : hasUnsavedChanges
    ? 'Save changes before running.'
    : '';
  // Publish button is disabled when there's no saved draft
  const isPublishDisabled = !hasPublishableDraft;

  const metadataFields = (
    <div
      className="builder-toolbar-metadata"
      style={{
        display: 'flex',
        flexDirection: isMobile ? 'column' : 'row',
        gap: isMobile ? '8px' : '12px',
        alignItems: isMobile ? 'stretch' : 'center',
        flexWrap: 'wrap',
      }}
    >
      <div style={FIELD_ROW_STYLE}>
        <label style={{ fontSize: '12px', fontWeight: '500' }}>Name:</label>
        <input
          type="text"
          value={workflowName}
          onChange={(e) => onChangeWorkflowName(e.target.value)}
          style={INPUT_STYLE}
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
              marginLeft: '4px',
              flex: '0 0 auto',
            }}
            title="Unsaved changes"
          />
        )}
      </div>

      <div style={FIELD_ROW_STYLE}>
        <label style={{ fontSize: '12px', fontWeight: '500' }}>Description:</label>
        <input
          type="text"
          value={description}
          onChange={(e) => onChangeDescription(e.target.value)}
          style={INPUT_STYLE}
        />
      </div>

      <div style={FIELD_ROW_STYLE}>
        <label style={{ fontSize: '12px', fontWeight: '500' }}>Provider:</label>
        <input
          type="text"
          value={provider}
          onChange={(e) => onChangeProvider(e.target.value)}
          style={INPUT_STYLE}
        />
      </div>

      <div style={FIELD_ROW_STYLE}>
        <label style={{ fontSize: '12px', fontWeight: '500' }}>Model:</label>
        <input
          type="text"
          value={model}
          onChange={(e) => onChangeModel(e.target.value)}
          style={INPUT_STYLE}
        />
      </div>
    </div>
  );

  return (
    <div
      className={`builder-toolbar${isMobile ? ' builder-toolbar--mobile' : ''}`}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        padding: '12px',
        borderBottom: '1px solid #ddd',
        backgroundColor: '#f9f9f9',
      }}
    >
      {/* Metadata inputs — hidden behind a disclosure on mobile to save vertical space */}
      {isMobile ? (
        <details className="builder-toolbar-metadata-disclosure">
          <summary
            style={{
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: '500',
              padding: '8px 0',
              minHeight: '44px',
              touchAction: 'manipulation',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            Workflow details
          </summary>
          <div style={{ marginTop: '8px' }}>{metadataFields}</div>
        </details>
      ) : (
        metadataFields
      )}

      {/* Action buttons and view mode toggle row */}
      <div
        style={{
          display: 'flex',
          gap: '8px',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <button onClick={onSave} style={{ ...BUTTON_BASE_STYLE, cursor: 'pointer' }}>
            Save
          </button>

          <button
            onClick={onPublish}
            disabled={isPublishDisabled}
            style={{
              ...BUTTON_BASE_STYLE,
              cursor: isPublishDisabled ? 'not-allowed' : 'pointer',
              opacity: isPublishDisabled ? 0.5 : 1,
            }}
          >
            Publish
          </button>

          <button
            onClick={onRun}
            disabled={isRunDisabled}
            title={runDisabledReason || 'Run workflow'}
            style={{
              ...BUTTON_BASE_STYLE,
              cursor: isRunDisabled ? 'not-allowed' : 'pointer',
              opacity: isRunDisabled ? 0.5 : 1,
            }}
          >
            Run
          </button>

          <button onClick={onValidate} style={{ ...BUTTON_BASE_STYLE, cursor: 'pointer' }}>
            Validate
          </button>

          <button onClick={onUndo} style={{ ...BUTTON_BASE_STYLE, cursor: 'pointer' }}>
            Undo
          </button>

          {onOpenVersions && (
            <button onClick={onOpenVersions} style={{ ...BUTTON_BASE_STYLE, cursor: 'pointer' }}>
              Versions
            </button>
          )}
        </div>

        {/* View mode toggle — hidden on mobile (canvas-only) */}
        {!isMobile && (
          <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
            <label style={{ fontSize: '12px', fontWeight: '500', marginRight: '4px' }}>
              YAML View:
            </label>
            <button
              onClick={() => onViewModeChange('hidden')}
              style={{
                ...VIEW_MODE_BUTTON_BASE_STYLE,
                backgroundColor: viewMode === 'hidden' ? '#007bff' : '#fff',
                color: viewMode === 'hidden' ? '#fff' : '#000',
                border: '1px solid #ccc',
                borderRadius: '4px 0 0 4px',
              }}
            >
              Hidden
            </button>
            <button
              onClick={() => onViewModeChange('split')}
              style={{
                ...VIEW_MODE_BUTTON_BASE_STYLE,
                backgroundColor: viewMode === 'split' ? '#007bff' : '#fff',
                color: viewMode === 'split' ? '#fff' : '#000',
                border: '1px solid #ccc',
                borderLeft: 'none',
                borderRight: 'none',
              }}
            >
              Split
            </button>
            <button
              onClick={() => onViewModeChange('full')}
              style={{
                ...VIEW_MODE_BUTTON_BASE_STYLE,
                backgroundColor: viewMode === 'full' ? '#007bff' : '#fff',
                color: viewMode === 'full' ? '#fff' : '#000',
                border: '1px solid #ccc',
                borderRadius: '0 4px 4px 0',
              }}
            >
              Full
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

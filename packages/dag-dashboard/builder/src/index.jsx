import React from 'react';
import { createRoot } from 'react-dom/client';

// Import @xyflow/react styles (will be bundled)
import '@xyflow/react/dist/style.css';

import { WorkflowCanvas } from './WorkflowCanvas.jsx';
import BuilderToolbar from './BuilderToolbar.jsx';
import useToolbarActions from './useToolbarActions.js';
import dagToYaml from './dagToYaml.js';

/**
 * Builder root. Integrates BuilderToolbar, WorkflowCanvas, and validation.
 * GW-5247: Added toolbar with Save/Publish/Run/Validate/Undo + view-mode toggle.
 */
function Builder() {
    const [dag, setDag] = React.useState([]);
    const [workflowName, setWorkflowName] = React.useState('untitled-workflow');
    const [description, setDescription] = React.useState('');
    const [provider, setProvider] = React.useState('');
    const [model, setModel] = React.useState('');
    const [viewMode, setViewMode] = React.useState('hidden');
    const [hasUnsavedChanges, setHasUnsavedChanges] = React.useState(false);
    const [hasClientErrors, setHasClientErrors] = React.useState(false);

    const toolbarActions = useToolbarActions(workflowName);

    // Access validation hook from global (loaded via separate script)
    // CRITICAL: Capture hook at module scope to avoid Rules of Hooks violation
    const validationHook = React.useMemo(
        () => window.DAGDashboardValidation?.useBuilderValidation || (() => ({ errors: [], warnings: [] })),
        []
    );
    const validation = validationHook(dag);

    React.useEffect(() => {
        setHasClientErrors(validation.errors.length > 0);
    }, [validation.errors]);

    const handleGraphChange = (newDag) => {
        setDag(newDag);
        setHasUnsavedChanges(true);
    };

    const handleSave = async () => {
        const yaml = dagToYaml({ name: workflowName, description, provider, model, dag });
        try {
            await toolbarActions.saveDraft(yaml);
            setHasUnsavedChanges(false);
        } catch (error) {
            console.error('Save failed:', error);
        }
    };

    const handlePublish = async () => {
        try {
            await toolbarActions.publishDraft();
        } catch (error) {
            console.error('Publish failed:', error);
        }
    };

    const handleRun = async () => {
        const yaml = dagToYaml({ name: workflowName, description, provider, model, dag });
        try {
            await toolbarActions.runWorkflow(yaml);
        } catch (error) {
            console.error('Run failed:', error);
        }
    };

    const handleValidate = async () => {
        const yaml = dagToYaml({ name: workflowName, description, provider, model, dag });
        try {
            const result = await toolbarActions.validateWorkflow(yaml);
            // ValidationPanel will handle displaying results via global state
            if (window.DAGDashboardValidation?.ValidationPanel) {
                console.log('Validation result:', result);
            }
        } catch (error) {
            console.error('Validate failed:', error);
        }
    };

    const handleUndo = () => {
        // Dispatch custom event that WorkflowCanvas listens for
        window.dispatchEvent(new CustomEvent('dag-builder:undo'));
    };

    const yaml = dagToYaml({ name: workflowName, description, provider, model, dag });

    return (
        <div
            style={{
                display: 'flex',
                flexDirection: 'column',
                height: '100%',
                minHeight: '600px',
                width: '100%',
                background: 'var(--bg-primary)',
                color: 'var(--text-primary)',
            }}
        >
            <BuilderToolbar
                workflowName={workflowName}
                description={description}
                provider={provider}
                model={model}
                viewMode={viewMode}
                hasUnsavedChanges={hasUnsavedChanges}
                hasClientErrors={hasClientErrors}
                hasPublishableDraft={!!toolbarActions.lastSavedTimestamp}
                onChangeWorkflowName={setWorkflowName}
                onChangeDescription={setDescription}
                onChangeProvider={setProvider}
                onChangeModel={setModel}
                onSave={handleSave}
                onPublish={handlePublish}
                onRun={handleRun}
                onValidate={handleValidate}
                onUndo={handleUndo}
                onViewModeChange={setViewMode}
            />

            <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
                <WorkflowCanvas
                    initialDag={dag}
                    readOnly={false}
                    onGraphChange={handleGraphChange}
                />

                {/* Placeholder for YamlCodeView (GW-5250) */}
                <div
                    id="yaml-view-mount"
                    data-view-mode={viewMode}
                    style={{
                        display: viewMode === 'hidden' ? 'none' : 'block',
                        width: viewMode === 'full' ? '100%' : '50%',
                        borderLeft: '1px solid #ddd',
                        padding: '8px',
                        overflow: 'auto'
                    }}
                >
                    {/* GW-5250 will mount YamlCodeView here */}
                    <div style={{ fontSize: '12px', color: '#666' }}>
                        YAML view placeholder (GW-5250)
                    </div>
                </div>
            </div>

            {/* Placeholder for ValidationPanel */}
            <div id="validation-panel-mount"></div>
        </div>
    );
}

/**
 * Mount function called by app.js when the /builder route is visited.
 * @param {HTMLElement} container - The DOM element to mount into
 */
export function mount(container) {
    if (!container) {
        console.error('DAGDashboardBuilder.mount: no container element provided');
        return;
    }
    // Give the container height so React Flow can size itself.
    container.style.height = '100%';
    container.style.minHeight = '600px';
    const root = createRoot(container);
    root.render(<Builder />);
}

// Export for global access
window.DAGDashboardBuilder = { mount };

import React from 'react';
import { createRoot } from 'react-dom/client';

// Import @xyflow/react styles (will be bundled)
import '@xyflow/react/dist/style.css';

import { WorkflowCanvas } from './WorkflowCanvas.jsx';
import BuilderToolbar from './BuilderToolbar.jsx';
import useToolbarActions from './useToolbarActions.js';
import { dagToYaml } from './dagToYaml.js';
import { YamlCodeView } from './YamlCodeView.jsx';

function serializeMetadata({ name, description, provider, model }) {
    const lines = [];
    if (name) lines.push(`name: ${quoteIfNeeded(name)}`);
    if (description) lines.push(`description: ${quoteIfNeeded(description)}`);
    if (provider) lines.push(`provider: ${quoteIfNeeded(provider)}`);
    if (model) lines.push(`model: ${quoteIfNeeded(model)}`);
    return lines.length > 0 ? lines.join('\n') + '\n' : '';
}

function quoteIfNeeded(str) {
    const s = String(str);
    if (s.includes(':') || s.includes('#') || /^\s|\s$/.test(s)) {
        return `"${s.replace(/"/g, '\\"')}"`;
    }
    return s;
}

function buildWorkflowYaml({ name, description, provider, model, dag }) {
    return serializeMetadata({ name, description, provider, model }) + dagToYaml(dag || []);
}

/**
 * Builder root. Integrates BuilderToolbar, WorkflowCanvas, YamlCodeView, and validation.
 * GW-5247: Added toolbar with Save/Publish/Run/Validate/Undo + view-mode toggle.
 * GW-5250: YamlCodeView read-only preview with split/full modes.
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

    // Access validation hook from global (loaded via separate script).
    // Capture the reference once to keep hook count stable across renders.
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
        const yaml = buildWorkflowYaml({ name: workflowName, description, provider, model, dag });
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
        const yaml = buildWorkflowYaml({ name: workflowName, description, provider, model, dag });
        try {
            await toolbarActions.runWorkflow(yaml);
        } catch (error) {
            console.error('Run failed:', error);
        }
    };

    const handleValidate = async () => {
        const yaml = buildWorkflowYaml({ name: workflowName, description, provider, model, dag });
        try {
            const result = await toolbarActions.validateWorkflow(yaml);
            if (window.DAGDashboardValidation?.ValidationPanel) {
                console.log('Validation result:', result);
            }
        } catch (error) {
            console.error('Validate failed:', error);
        }
    };

    const handleUndo = () => {
        window.dispatchEvent(new CustomEvent('dag-builder:undo'));
    };

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

            <div
                style={{
                    display: 'flex',
                    flexDirection: 'row',
                    flex: 1,
                    overflow: 'hidden',
                }}
            >
                {/* Canvas - hidden in full mode but still mounted to preserve state */}
                <div
                    style={{
                        display: viewMode === 'full' ? 'none' : 'flex',
                        flex: viewMode === 'split' ? '0 0 60%' : '1',
                        minWidth: 0,
                    }}
                >
                    <WorkflowCanvas
                        initialDag={dag}
                        readOnly={false}
                        onGraphChange={handleGraphChange}
                    />
                </div>

                {/* YAML preview - shown in split and full modes (GW-5250) */}
                {viewMode !== 'hidden' && (
                    <div
                        style={{
                            flex: viewMode === 'split' ? '0 0 40%' : '1',
                            minWidth: 0,
                            overflow: 'auto',
                        }}
                    >
                        <YamlCodeView dag={dag} viewMode={viewMode} />
                    </div>
                )}
            </div>

            {/* Placeholder for ValidationPanel (feature-flagged global script) */}
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
    container.style.height = '100%';
    container.style.minHeight = '600px';
    const root = createRoot(container);
    root.render(<Builder />);
}

window.DAGDashboardBuilder = { mount };

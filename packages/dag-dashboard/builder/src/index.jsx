import React from 'react';
import { createRoot } from 'react-dom/client';

// Import @xyflow/react styles (will be bundled)
import '@xyflow/react/dist/style.css';

import { WorkflowCanvas } from './WorkflowCanvas.jsx';
import BuilderToolbar from './BuilderToolbar.jsx';
import useToolbarActions from './useToolbarActions.js';
import { dagToYaml } from './dagToYaml.js';
import { useAutosave } from './useAutosave.js';
import { YamlCodeView } from './YamlCodeView.jsx';
import VersionDrawer from './VersionDrawer.jsx';
import useVersionDrawer from './useVersionDrawer.js';

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
 * Builder root. Integrates BuilderToolbar (GW-5247), WorkflowCanvas,
 * YamlCodeView (GW-5250), and autosave (GW-5248) into a single workflow editor.
 *
 * The workflow name is initialized from the ?workflow= query param and becomes
 * editable state — autosave tracks it, and the toolbar surfaces it for edit.
 */
function Builder() {
    const [initialDag, setInitialDag] = React.useState(null);
    const [dag, setDag] = React.useState([]);
    const dagRef = React.useRef([]);
    const [isLoaded, setIsLoaded] = React.useState(false);
    const [restoreKey, setRestoreKey] = React.useState(0);
    const [viewMode, setViewMode] = React.useState('hidden');
    const [description, setDescription] = React.useState('');
    const [provider, setProvider] = React.useState('');
    const [model, setModel] = React.useState('');
    const [hasClientErrors, setHasClientErrors] = React.useState(false);
    const [allowDestructiveNodes, setAllowDestructiveNodes] = React.useState(false);

    // Workflow name: initialize from ?workflow= but remain editable.
    const initialWorkflowName = React.useMemo(() => {
        const params = new URLSearchParams(window.location.search);
        return params.get('workflow') || 'untitled';
    }, []);
    const [workflowName, setWorkflowName] = React.useState(initialWorkflowName);

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

    // Fetch allow_destructive_nodes config flag on mount
    React.useEffect(() => {
        fetch('/api/config')
            .then(res => res.json())
            .then(data => {
                setAllowDestructiveNodes(data.allow_destructive_nodes || false);
            })
            .catch(err => {
                console.error('Failed to fetch config:', err);
                setAllowDestructiveNodes(false);
            });
    }, []);

    // Stable getDag reference for useAutosave
    const getDag = React.useCallback(() => dagRef.current, []);

    // Stable onLoad callback for useAutosave — called once the initial draft loads.
    const onLoad = React.useCallback((loadedDag) => {
        setInitialDag(loadedDag);
        setIsLoaded(true);
    }, []);

    // Autosave hook (GW-5248) — debounced background save to current draft timestamp.
    const { status, forceSave, lastSavedAt, markDirty } = useAutosave({
        workflowName,
        getDag,
        onLoad,
    });

    // Version drawer hook (GW-5251) — manage version browser state and actions.
    // Pass JSON format to match draft storage format for apples-to-apples diff
    const currentCanvasJson = React.useMemo(
        () => JSON.stringify({ nodes: dag }),
        [dag]
    );
    const versionDrawer = useVersionDrawer(workflowName, currentCanvasJson);

    // Restore handler — loads draft nodes and forces canvas remount via restoreKey.
    const handleRestore = React.useCallback(async (timestamp) => {
        const nodes = await versionDrawer.handleRestore(timestamp);
        if (nodes) {
            setInitialDag(nodes);
            setRestoreKey(prev => prev + 1);
            versionDrawer.close();
        }
    }, [versionDrawer]);

    // Keyboard handler for Cmd/Ctrl+S — force save.
    React.useEffect(() => {
        const handleKeyDown = (e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 's') {
                e.preventDefault();
                forceSave();
            }
        };
        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [forceSave]);

    // Keep dagRef + dag state + autosave dirty flag in sync.
    const handleGraphChange = React.useCallback((nextDag) => {
        dagRef.current = nextDag;
        setDag(nextDag);
        markDirty();
    }, [markDirty]);

    // Autosave-driven unsaved indicator.
    const hasUnsavedChanges = status === 'unsaved' || status === 'saving';

    // Toolbar action wrappers.
    const handleSave = React.useCallback(() => {
        // Force-save creates a new timestamp, matching AC: "Save creates a new draft on every click".
        forceSave();
    }, [forceSave]);

    const handlePublish = React.useCallback(async () => {
        try {
            await toolbarActions.publishDraft();
        } catch (error) {
            console.error('Publish failed:', error);
        }
    }, [toolbarActions]);

    const handleRun = React.useCallback(async () => {
        const yaml = buildWorkflowYaml({ name: workflowName, description, provider, model, dag });
        try {
            await toolbarActions.runWorkflow(yaml);
        } catch (error) {
            console.error('Run failed:', error);
        }
    }, [toolbarActions, workflowName, description, provider, model, dag]);

    const handleValidate = React.useCallback(async () => {
        const yaml = buildWorkflowYaml({ name: workflowName, description, provider, model, dag });
        try {
            const result = await toolbarActions.validateWorkflow(yaml);
            if (window.DAGDashboardValidation?.ValidationPanel) {
                console.log('Validation result:', result);
            }
        } catch (error) {
            console.error('Validate failed:', error);
        }
    }, [toolbarActions, workflowName, description, provider, model, dag]);

    const handleUndo = React.useCallback(() => {
        window.dispatchEvent(new CustomEvent('dag-builder:undo'));
    }, []);

    // Optional secondary status line (GW-5248 behaviour).
    const saveStatus = React.useMemo(() => {
        if (status === 'saving') return 'Saving...';
        if (status === 'saved' && lastSavedAt) {
            const elapsed = Math.floor((Date.now() - lastSavedAt) / 1000);
            if (elapsed < 60) return `Saved ${elapsed}s ago`;
            return 'Saved';
        }
        if (status === 'unsaved') return 'Unsaved changes';
        if (status === 'error') return 'Save failed';
        return '';
    }, [status, lastSavedAt]);

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
                onOpenVersions={versionDrawer.open}
            />

            {!allowDestructiveNodes && (
                <div className="builder-safety-banner builder-safety-banner-restricted">
                    ⓘ Bash/skill/command node fields are read-only. To enable editing, visit <a href="#/settings">Settings</a>.
                </div>
            )}

            {allowDestructiveNodes && (
                <div className="builder-safety-banner builder-safety-banner-warning">
                    ⚠️ Destructive node editing is enabled. Users can modify bash commands and skill references.
                </div>
            )}

            {saveStatus && (
                <div
                    style={{
                        padding: '4px 8px',
                        fontSize: '12px',
                        color: 'var(--text-secondary, #888)',
                        borderBottom: '1px solid var(--border-primary, #333)',
                    }}
                >
                    {saveStatus}
                </div>
            )}

            {!isLoaded ? (
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        flex: 1,
                        color: 'var(--text-secondary, #888)',
                    }}
                >
                    Loading workflow...
                </div>
            ) : (
                <div
                    style={{
                        display: 'flex',
                        flexDirection: 'row',
                        flex: 1,
                        overflow: 'hidden',
                    }}
                >
                    {/* Canvas — hidden in full mode but still mounted to preserve state */}
                    <div
                        style={{
                            display: viewMode === 'full' ? 'none' : 'flex',
                            flex: viewMode === 'split' ? '0 0 60%' : '1',
                            minWidth: 0,
                        }}
                    >
                        <WorkflowCanvas
                            key={`${isLoaded ? 'loaded' : 'loading'}-${restoreKey}`}
                            initialDag={initialDag}
                            readOnly={false}
                            allowDestructiveNodes={allowDestructiveNodes}
                            onGraphChange={handleGraphChange}
                        />
                    </div>

                    {/* YAML preview (GW-5250) — shown in split and full modes */}
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
            )}

            {/* Placeholder for ValidationPanel (feature-flagged global script) */}
            <div id="validation-panel-mount"></div>

            {/* Version Drawer (GW-5251) */}
            <VersionDrawer
                isOpen={versionDrawer.isOpen}
                drafts={versionDrawer.drafts}
                hoveredDiff={versionDrawer.hoveredDiff}
                onClose={versionDrawer.close}
                onRestore={handleRestore}
                onDelete={versionDrawer.handleDelete}
                onHover={versionDrawer.handleHover}
            />
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

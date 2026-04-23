import React from 'react';
import { createRoot } from 'react-dom/client';

// Import @xyflow/react styles (will be bundled)
import '@xyflow/react/dist/style.css';

import { WorkflowCanvas } from './WorkflowCanvas.jsx';
import { useAutosave } from './useAutosave.js';
import { YamlCodeView } from './YamlCodeView.jsx';

/**
 * Builder root with autosave. Reads workflow name from ?workflow= query param
 * (defaults to "untitled"), loads the most recent draft via .current pointer,
 * and autosaves every 30s after the last edit. Cmd/Ctrl+S triggers a manual
 * save (creates a new timestamp).
 */
function Builder() {
    const [initialDag, setInitialDag] = React.useState(null);
    const [dag, setDag] = React.useState([]);
    const dagRef = React.useRef([]);
    const [isLoaded, setIsLoaded] = React.useState(false);
    const [viewMode, setViewMode] = React.useState('hidden');

    // Read workflow name from URL
    const workflowName = React.useMemo(() => {
        const params = new URLSearchParams(window.location.search);
        return params.get('workflow') || 'untitled';
    }, []);

    // Stable getDag reference
    const getDag = React.useCallback(() => dagRef.current, []);

    // Stable onLoad callback
    const onLoad = React.useCallback((dag) => {
        setInitialDag(dag);
        setIsLoaded(true);
    }, []);

    // Autosave hook
    const { status, forceSave, lastSavedAt, markDirty } = useAutosave({
        workflowName,
        getDag,
        onLoad
    });

    // Keyboard handler for Cmd/Ctrl+S
    React.useEffect(() => {
        const handleKeyDown = (e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 's') {
                e.preventDefault();
                forceSave();
            }
        };

        document.addEventListener('keydown', handleKeyDown);
        return () => {
            document.removeEventListener('keydown', handleKeyDown);
        };
    }, [forceSave]);

    // Handle graph changes
    const handleGraphChange = React.useCallback((nextDag) => {
        dagRef.current = nextDag;
        setDag(nextDag);
        markDirty();
    }, [markDirty]);

    // Save status indicator
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
            {/* Save status indicator */}
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

            {/* View mode toolbar */}
            <div className="yaml-preview-toolbar">
                <button
                    onClick={() => setViewMode('hidden')}
                    className={viewMode === 'hidden' ? 'active' : ''}
                    aria-label="Hide YAML preview"
                >
                    Canvas Only
                </button>
                <button
                    onClick={() => setViewMode('split')}
                    className={viewMode === 'split' ? 'active' : ''}
                    aria-label="Show split view"
                >
                    Split View
                </button>
                <button
                    onClick={() => setViewMode('full')}
                    className={viewMode === 'full' ? 'active' : ''}
                    aria-label="Show YAML preview only"
                >
                    YAML Only
                </button>
            </div>

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
                /* Main content area with conditional layout */
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
                            minWidth: 0, // Allow flex shrink
                        }}
                    >
                        <WorkflowCanvas
                            key={isLoaded ? 'loaded' : 'loading'}
                            initialDag={initialDag}
                            readOnly={false}
                            onGraphChange={handleGraphChange}
                        />
                    </div>

                    {/* YAML preview - shown in split and full modes */}
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

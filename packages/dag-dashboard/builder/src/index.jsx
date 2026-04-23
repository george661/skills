import React from 'react';
import { createRoot } from 'react-dom/client';

// Import @xyflow/react styles (will be bundled)
import '@xyflow/react/dist/style.css';

import { WorkflowCanvas } from './WorkflowCanvas.jsx';
import { YamlCodeView } from './YamlCodeView.jsx';

/**
 * Builder root. Mounts the React Flow-based canvas into the container
 * provided by the dashboard router. The NodeLibrary palette (GW-5245)
 * and NodeInspector form (GW-5244) are separate components; wiring
 * them together into a full three-pane layout is a later Tier B task.
 *
 * For now, the canvas stands alone and accepts drops in the library's
 * `application/x-dag-node` format so that when the integration task
 * lands it is a wiring change, not a refactor.
 */
function Builder() {
    const [dag, setDag] = React.useState([]);
    const [viewMode, setViewMode] = React.useState('hidden');

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

            {/* Main content area with conditional layout */}
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
                        initialDag={[]}
                        readOnly={false}
                        onGraphChange={setDag}
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

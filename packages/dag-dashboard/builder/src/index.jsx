import React from 'react';
import { createRoot } from 'react-dom/client';

// Import @xyflow/react styles (will be bundled)
import '@xyflow/react/dist/style.css';

import { WorkflowCanvas } from './WorkflowCanvas.jsx';

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
    const [, setDag] = React.useState([]);
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
            <WorkflowCanvas
                initialDag={[]}
                readOnly={false}
                onGraphChange={setDag}
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
    // Give the container height so React Flow can size itself.
    container.style.height = '100%';
    container.style.minHeight = '600px';
    const root = createRoot(container);
    root.render(<Builder />);
}

// Export for global access
window.DAGDashboardBuilder = { mount };

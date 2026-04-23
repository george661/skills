import React from 'react';
import { createRoot } from 'react-dom/client';
import { ReactFlow } from '@xyflow/react';
import dagre from 'dagre';

// Import @xyflow/react styles (will be bundled)
import '@xyflow/react/dist/style.css';

/**
 * Placeholder Builder component.
 * Task 4 (GW-5242) delivers only the vendored bundle plumbing.
 * Task 5+ (GW-5243 onward) will port Archon components.
 */
function Builder() {
    return (
        <div style={{
            padding: '2rem',
            fontFamily: 'system-ui, -apple-system, sans-serif',
            maxWidth: '800px',
            margin: '0 auto'
        }}>
            <h1 style={{ fontSize: '2rem', marginBottom: '1rem' }}>
                DAG Builder
            </h1>
            <p style={{ fontSize: '1rem', color: '#666', marginBottom: '1rem' }}>
                Coming soon. This placeholder proves the React + React Flow + dagre bundle is loaded.
            </p>
            <div style={{
                padding: '1rem',
                background: '#f0f0f0',
                borderRadius: '4px',
                fontSize: '0.875rem',
                fontFamily: 'monospace'
            }}>
                <div>✓ React: {React.version}</div>
                <div>✓ @xyflow/react: loaded</div>
                <div>✓ dagre: loaded</div>
            </div>
            <p style={{ fontSize: '0.875rem', color: '#999', marginTop: '1rem' }}>
                Feature flag: DAG_DASHBOARD_BUILDER_ENABLED = true
            </p>
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

    const root = createRoot(container);
    root.render(<Builder />);
}

// Export for global access
window.DAGDashboardBuilder = { mount };

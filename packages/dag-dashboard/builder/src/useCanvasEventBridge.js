import { useEffect } from 'react';

/**
 * Hook that bridges DOM events from NodeInspector to canvas state updates.
 * Extracted for testability without DOM (GW-5332).
 * 
 * @param {Function} updateNode - Callback to update a node in canvas state
 * @param {Function} onNodesDelete - Callback to delete nodes from canvas state
 */
export function useCanvasEventBridge(updateNode, onNodesDelete) {
    // Listen for node-update event from inspector
    useEffect(() => {
        const handler = (e) => {
            if (e.detail && updateNode) updateNode(e.detail);
        };
        if (typeof document !== 'undefined') document.addEventListener('dag-builder:node-update', handler);
        return () => {
            if (typeof document !== 'undefined') document.removeEventListener('dag-builder:node-update', handler);
        };
    }, [updateNode]);

    // Listen for node-delete event from inspector
    useEffect(() => {
        const handler = (e) => {
            if (e.detail && onNodesDelete) onNodesDelete([{ id: e.detail }]);
        };
        if (typeof document !== 'undefined') document.addEventListener('dag-builder:node-delete', handler);
        return () => {
            if (typeof document !== 'undefined') document.removeEventListener('dag-builder:node-delete', handler);
        };
    }, [onNodesDelete]);
}

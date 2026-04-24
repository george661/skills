import { useEffect, useRef } from 'react';

/**
 * Hook that manages NodeInspector lifecycle and event dispatching.
 * Extracted for testability without DOM (GW-5332).
 * 
 * @param {Object} options
 * @param {Object} options.selectedNode - The currently selected node
 * @param {boolean} options.allowDestructive - Whether destructive operations are allowed
 * @param {Array<string>} options.availableNodeIds - List of available node IDs for references
 * @param {Object} options.containerRef - React ref pointing to the DOM container element
 * @returns {Object} inspectorInstanceRef - Ref to the NodeInspector instance
 */
export function useNodeInspector({ selectedNode, allowDestructive, availableNodeIds, containerRef }) {
    const inspectorInstanceRef = useRef(null);

    useEffect(() => {
        // Destroy existing instance if any
        if (inspectorInstanceRef.current) {
            inspectorInstanceRef.current.destroy();
            inspectorInstanceRef.current = null;
        }

        // Create new instance if node selected and container available
        if (selectedNode && containerRef.current && typeof window !== 'undefined' && window.NodeInspector) {
            inspectorInstanceRef.current = new window.NodeInspector({
                container: containerRef.current,
                node: selectedNode,
                allowDestructive: allowDestructive,
                availableNodeIds: availableNodeIds,
                onChange: (updatedNode) => {
                    if (typeof document !== 'undefined' && typeof CustomEvent === 'function') {
                        document.dispatchEvent(
                            new CustomEvent('dag-builder:node-update', { detail: updatedNode })
                        );
                    }
                },
                onDelete: (nodeId) => {
                    if (typeof document !== 'undefined' && typeof CustomEvent === 'function') {
                        document.dispatchEvent(
                            new CustomEvent('dag-builder:node-delete', { detail: nodeId })
                        );
                    }
                },
            });
        }

        // Cleanup on unmount or when dependencies change
        return () => {
            if (inspectorInstanceRef.current) {
                inspectorInstanceRef.current.destroy();
                inspectorInstanceRef.current = null;
            }
        };
    }, [selectedNode, allowDestructive, availableNodeIds, containerRef]);

    return inspectorInstanceRef;
}

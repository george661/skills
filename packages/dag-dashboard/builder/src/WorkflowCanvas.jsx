/**
 * React Flow canvas shell for the builder. Thin wrapper over
 * `useCanvasState` — all state and handlers live in the hook so unit
 * tests can drive the behavior without a DOM.
 *
 * Integration with sibling components:
 * - NodeLibrary (GW-5245) drops items using dataTransfer key
 *   `application/x-dag-node` carrying `{kind, payload}`. The hook's
 *   `onDrop` parses that format.
 * - NodeInspector (GW-5244) is vanilla JS loaded via <script>. This
 *   canvas dispatches a `dag-builder:node-selected` CustomEvent when
 *   selection changes; host code wires it into the inspector. Keeping
 *   the coupling loose means the inspector doesn't need to be inside
 *   the React tree.
 */
import React, { useCallback, useMemo, useEffect } from 'react';
import {
    ReactFlow,
    ReactFlowProvider,
    Background,
    Controls,
    MiniMap,
    useReactFlow,
} from '@xyflow/react';

import { useCanvasState } from './useCanvasState.js';
import { makeNodeTypes } from './DagNode.jsx';

function CanvasInner({ initialDag, readOnly, onGraphChange }) {
    const rf = useReactFlow();
    const flowToPosition = useCallback(
        (screen) => {
            if (!rf || typeof rf.screenToFlowPosition !== 'function') return screen;
            return rf.screenToFlowPosition(screen);
        },
        [rf],
    );

    const state = useCanvasState(initialDag, { flowToPosition });
    const { nodes, edges, onConnect, onNodesDelete, onEdgesDelete, onDrop, undo, toDag } = state;

    const nodeTypes = useMemo(() => makeNodeTypes({ readOnly }), [readOnly]);

    // Propagate graph changes upward for host integrations (save, yaml preview)
    useEffect(() => {
        if (typeof onGraphChange === 'function') onGraphChange(toDag());
    }, [nodes, edges, onGraphChange, toDag]);

    // Cmd/Ctrl+Z → undo last delete (single level; full history is FR-10)
    useEffect(() => {
        const handler = (e) => {
            const mod = e.metaKey || e.ctrlKey;
            if (mod && !e.shiftKey && (e.key === 'z' || e.key === 'Z')) {
                e.preventDefault();
                undo();
            }
        };
        if (typeof document !== 'undefined') document.addEventListener('keydown', handler);
        return () => {
            if (typeof document !== 'undefined') document.removeEventListener('keydown', handler);
        };
    }, [undo]);

    const onDragOver = useCallback((event) => {
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
    }, []);

    const onSelectionChange = useCallback(({ nodes: selectedNodes }) => {
        const selected = Array.isArray(selectedNodes) && selectedNodes.length > 0 ? selectedNodes[0] : null;
        if (typeof document !== 'undefined' && typeof CustomEvent === 'function') {
            document.dispatchEvent(
                new CustomEvent('dag-builder:node-selected', {
                    detail: selected ? (selected.data && selected.data.raw) || null : null,
                }),
            );
        }
    }, []);

    return (
        <div
            className="workflow-canvas"
            style={{ flex: 1, minWidth: 0, height: '100%', position: 'relative' }}
            onDrop={onDrop}
            onDragOver={onDragOver}
        >
            <ReactFlow
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                onConnect={onConnect}
                onNodesDelete={onNodesDelete}
                onEdgesDelete={onEdgesDelete}
                onSelectionChange={onSelectionChange}
                deleteKeyCode={['Delete', 'Backspace']}
                fitView
                nodesDraggable={!readOnly}
                nodesConnectable={!readOnly}
                elementsSelectable
            >
                <Background />
                <Controls />
                <MiniMap pannable zoomable />
            </ReactFlow>
        </div>
    );
}

export function WorkflowCanvas({ initialDag = [], readOnly = false, onGraphChange }) {
    return (
        <ReactFlowProvider>
            <CanvasInner initialDag={initialDag} readOnly={readOnly} onGraphChange={onGraphChange} />
        </ReactFlowProvider>
    );
}

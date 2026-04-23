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
import { useBuilderKeyboard } from './useBuilderKeyboard.js';
import { makeNodeTypes } from './DagNode.jsx';

function CanvasInner({
    initialDag,
    readOnly,
    onGraphChange,
    onSave,
    onRun,
    onToggleYaml,
    onToggleValidation,
    onToggleLibrary,
    onDuplicate,
}) {
    const rf = useReactFlow();
    const flowToPosition = useCallback(
        (screen) => {
            if (!rf || typeof rf.screenToFlowPosition !== 'function') return screen;
            return rf.screenToFlowPosition(screen);
        },
        [rf],
    );

    const state = useCanvasState(initialDag, { flowToPosition });
    const { nodes, edges, onConnect, onNodesDelete, onEdgesDelete, onDrop, undo, redo, toDag } = state;

    const nodeTypes = useMemo(() => makeNodeTypes({ readOnly }), [readOnly]);

    // Propagate graph changes upward for host integrations (save, yaml preview)
    useEffect(() => {
        if (typeof onGraphChange === 'function') onGraphChange(toDag());
    }, [nodes, edges, onGraphChange, toDag]);

    // Wire up keyboard shortcuts
    const shortcuts = useMemo(() => ({
        'mod+s': onSave || (() => {}),
        'mod+z': undo,
        'mod+shift+z': redo,
        'mod+/': onToggleYaml || (() => {}),
        'mod+.': onToggleValidation || (() => {}),
        'mod+enter': onRun || (() => {}),
        'mod+l': onToggleLibrary || (() => {}),
        'mod+d': onDuplicate || (() => {}),
        'delete': () => {
            // Delete is handled by React Flow's deleteKeyCode prop
            // We register it here for completeness but React Flow will fire onNodesDelete
        },
    }), [onSave, undo, redo, onToggleYaml, onToggleValidation, onRun, onToggleLibrary, onDuplicate]);

    useBuilderKeyboard(shortcuts, { enabled: !readOnly });

    // Listen for undo event from toolbar
    useEffect(() => {
        const handler = () => undo();
        if (typeof window !== 'undefined') window.addEventListener('dag-builder:undo', handler);
        return () => {
            if (typeof window !== 'undefined') window.removeEventListener('dag-builder:undo', handler);
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
                panOnDrag
                panOnScroll={false}
                zoomOnPinch
                zoomOnScroll
                minZoom={0.25}
                maxZoom={2.0}
            >
                <Background />
                <Controls />
                <MiniMap pannable zoomable />
            </ReactFlow>
        </div>
    );
}

export function WorkflowCanvas({
    initialDag = [],
    readOnly = false,
    onGraphChange,
    onSave,
    onRun,
    onToggleYaml,
    onToggleValidation,
    onToggleLibrary,
    onDuplicate,
}) {
    return (
        <ReactFlowProvider>
            <CanvasInner
                initialDag={initialDag}
                readOnly={readOnly}
                onGraphChange={onGraphChange}
                onSave={onSave}
                onRun={onRun}
                onToggleYaml={onToggleYaml}
                onToggleValidation={onToggleValidation}
                onToggleLibrary={onToggleLibrary}
                onDuplicate={onDuplicate}
            />
        </ReactFlowProvider>
    );
}

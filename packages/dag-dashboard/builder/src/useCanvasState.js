/**
 * Pure React hook managing canvas state: nodes, edges, and the handlers
 * that React Flow fires on user interaction.
 *
 * Design note: this hook is deliberately decoupled from @xyflow/react so
 * behavior tests can drive it under react-test-renderer without a DOM.
 * The <WorkflowCanvas> component wraps this hook and passes state to
 * React Flow's own components.
 *
 * Single-level undo (last delete only) ships in this task; full 50-step
 * history per PRP-PLAT-008 FR-10 is a later task.
 */
import { useState, useRef, useCallback } from 'react';

import { dagToReactFlow, reactFlowToDag, applyDagreLayout } from './dagToReactFlow.js';

let idCounter = 0;
function generateId(prefix) {
    idCounter += 1;
    return `${prefix}_${Date.now()}_${idCounter}`;
}

/**
 * @param {Array<object>} initialDag - dag-executor node list (may be empty)
 * @param {object} [opts]
 * @returns {{
 *   nodes: Array, edges: Array,
 *   setGraph: Function,
 *   onConnect: Function,
 *   onNodesDelete: Function,
 *   onEdgesDelete: Function,
 *   onDrop: Function,
 *   undo: Function,
 *   canUndo: boolean,
 *   toDag: Function,
 * }}
 */
export function useCanvasState(initialDag = [], opts = {}) {
    const initial = applyDagreLayout(dagToReactFlow(initialDag));
    const [graph, setGraph] = useState(initial);
    const lastDeleteRef = useRef(null);

    const onConnect = useCallback((params) => {
        if (!params || !params.source || !params.target) return;
        const { source, target } = params;
        setGraph(prev => {
            if (prev.edges.some(e => e.source === source && e.target === target)) return prev;
            if (source === target) return prev; // no self-loops
            return {
                ...prev,
                edges: [...prev.edges, { id: `${source}->${target}`, source, target }],
            };
        });
    }, []);

    const onNodesDelete = useCallback((deleted) => {
        if (!Array.isArray(deleted) || deleted.length === 0) return;
        const deletedIds = new Set(deleted.map(n => n.id));
        setGraph(prev => {
            const removedNodes = prev.nodes.filter(n => deletedIds.has(n.id));
            const removedEdges = prev.edges.filter(e => deletedIds.has(e.source) || deletedIds.has(e.target));
            lastDeleteRef.current = { nodes: removedNodes, edges: removedEdges };
            return {
                nodes: prev.nodes.filter(n => !deletedIds.has(n.id)),
                edges: prev.edges.filter(e => !deletedIds.has(e.source) && !deletedIds.has(e.target)),
            };
        });
    }, []);

    const onEdgesDelete = useCallback((deleted) => {
        if (!Array.isArray(deleted) || deleted.length === 0) return;
        const deletedIds = new Set(deleted.map(e => e.id));
        setGraph(prev => ({
            ...prev,
            edges: prev.edges.filter(e => !deletedIds.has(e.id)),
        }));
    }, []);

    /**
     * Accepts a drop event whose dataTransfer carries either NodeLibrary's
     * format (`application/x-dag-node` → {kind, payload}) or a bare node
     * type string (`application/x-dag-node-type`) for tests and future
     * palette variants.
     */
    const onDrop = useCallback((event) => {
        if (!event || !event.dataTransfer) return;
        if (typeof event.preventDefault === 'function') event.preventDefault();

        const libraryData = event.dataTransfer.getData('application/x-dag-node');
        const typeOnly = event.dataTransfer.getData('application/x-dag-node-type');

        let nodeShape = null;
        if (libraryData) {
            try {
                const parsed = JSON.parse(libraryData);
                nodeShape = buildNodeFromLibraryDrop(parsed);
            } catch {
                // malformed payload — ignore
            }
        } else if (typeOnly) {
            nodeShape = buildNodeFromLibraryDrop({ kind: 'node-type', payload: { name: typeOnly } });
        }

        if (!nodeShape) return;

        const position = resolveDropPosition(event, opts.flowToPosition);
        setGraph(prev => ({
            ...prev,
            nodes: [
                ...prev.nodes,
                {
                    id: nodeShape.id,
                    type: nodeShape.type,
                    position,
                    data: {
                        node_type: nodeShape.type,
                        name: nodeShape.name,
                        id: nodeShape.id,
                        summary: '',
                        raw: nodeShape,
                    },
                },
            ],
        }));
    }, [opts.flowToPosition]);

    const undo = useCallback(() => {
        const last = lastDeleteRef.current;
        if (!last) return;
        lastDeleteRef.current = null;
        setGraph(prev => ({
            nodes: [...prev.nodes, ...last.nodes],
            edges: [...prev.edges, ...last.edges],
        }));
    }, []);

    const canUndo = lastDeleteRef.current != null;

    const toDag = useCallback(() => reactFlowToDag(graph), [graph]);

    return {
        nodes: graph.nodes,
        edges: graph.edges,
        setGraph,
        onConnect,
        onNodesDelete,
        onEdgesDelete,
        onDrop,
        undo,
        canUndo,
        toDag,
    };
}

function buildNodeFromLibraryDrop(parsed) {
    if (!parsed || typeof parsed !== 'object') return null;
    const { kind, payload } = parsed;
    if (!payload) return null;

    if (kind === 'node-type') {
        const nodeType = payload.name;
        if (!nodeType) return null;
        return {
            id: generateId(nodeType),
            type: nodeType,
            name: nodeType,
        };
    }
    if (kind === 'command') {
        return {
            id: generateId('command'),
            type: 'command',
            name: payload.name || 'command',
            command: payload.name,
        };
    }
    if (kind === 'skill') {
        return {
            id: generateId('skill'),
            type: 'skill',
            name: payload.name || 'skill',
            skill: payload.path || payload.name,
        };
    }
    return null;
}

function resolveDropPosition(event, flowToPosition) {
    if (typeof flowToPosition === 'function') {
        const pos = flowToPosition({ x: event.clientX, y: event.clientY });
        if (pos && Number.isFinite(pos.x) && Number.isFinite(pos.y)) return pos;
    }
    return {
        x: Number.isFinite(event.clientX) ? event.clientX : 0,
        y: Number.isFinite(event.clientY) ? event.clientY : 0,
    };
}

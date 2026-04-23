/**
 * Pure conversion between dag-executor NodeDef shape and React Flow's
 * {nodes, edges} shape. Dagre auto-layout is a thin wrapper over the
 * bundled `dagre` package — not a reimplementation of layout.py
 * (which is the server-side SVG renderer's layout).
 *
 * This module has NO React imports. It is unit-tested directly under
 * Node's built-in test runner via an esbuild pre-transform step.
 */
import dagre from 'dagre';

const DEFAULT_NODE_WIDTH = 200;
const DEFAULT_NODE_HEIGHT = 80;

/**
 * Convert dag-executor node list to React Flow {nodes, edges}.
 * `depends_on` on a node populates an incoming edge from each parent.
 * Conditional `edges:` on a node are out of scope here — the builder
 * emits simple depends_on lists; the server-side executor handles the
 * full EdgeDef conversion for runs (see dag-executor/schema.py EdgeDef).
 *
 * @param {Array<{id:string,name?:string,type?:string,depends_on?:string[]}>} dagNodes
 * @returns {{nodes: Array, edges: Array}}
 */
export function dagToReactFlow(dagNodes) {
    if (!Array.isArray(dagNodes)) return { nodes: [], edges: [] };

    const nodes = dagNodes.map(n => ({
        id: n.id,
        type: n.type || 'bash',
        position: { x: 0, y: 0 },
        data: {
            node_type: n.type || 'bash',
            name: n.name || n.id,
            id: n.id,
            summary: summarize(n),
            raw: n,
        },
    }));

    const edges = [];
    for (const n of dagNodes) {
        const parents = Array.isArray(n.depends_on) ? n.depends_on : [];
        for (const parent of parents) {
            edges.push({
                id: `${parent}->${n.id}`,
                source: parent,
                target: n.id,
            });
        }
    }

    return { nodes, edges };
}

/**
 * Convert React Flow {nodes, edges} back to dag-executor node list,
 * stripping positions and React Flow metadata.
 *
 * Edges populate `depends_on` — the builder's authoring surface uses
 * simple dependencies only; conditional edges live in the source YAML
 * and round-trip via data.raw.
 *
 * @param {{nodes: Array, edges: Array}} graph
 * @returns {Array<object>}
 */
export function reactFlowToDag({ nodes, edges }) {
    if (!Array.isArray(nodes)) return [];
    const dependsBy = new Map();
    const edgeList = Array.isArray(edges) ? edges : [];
    for (const edge of edgeList) {
        const list = dependsBy.get(edge.target) || [];
        list.push(edge.source);
        dependsBy.set(edge.target, list);
    }
    return nodes.map(n => {
        const raw = (n.data && n.data.raw) || {};
        const depends = dependsBy.get(n.id) || [];
        const out = {
            ...raw,
            id: n.id,
            type: (n.data && n.data.node_type) || raw.type || 'bash',
            name: (n.data && n.data.name) || raw.name || n.id,
        };
        if (depends.length > 0) out.depends_on = depends;
        else if ('depends_on' in out && out.depends_on && out.depends_on.length === 0) {
            delete out.depends_on;
        } else if (depends.length === 0) {
            delete out.depends_on;
        }
        return out;
    });
}

/**
 * Apply Dagre layout in-place on React Flow {nodes, edges} — assigns
 * a `position: {x, y}` to each node. Direction is top-to-bottom
 * (`rankdir: 'TB'`) matching the server-side SVG renderer's orientation.
 *
 * @param {{nodes: Array, edges: Array}} graph
 * @param {object} [opts] - optional {nodeWidth, nodeHeight, nodesep, ranksep}
 * @returns {{nodes: Array, edges: Array}}
 */
export function applyDagreLayout({ nodes, edges }, opts = {}) {
    const nodeWidth = opts.nodeWidth || DEFAULT_NODE_WIDTH;
    const nodeHeight = opts.nodeHeight || DEFAULT_NODE_HEIGHT;
    const nodesep = opts.nodesep != null ? opts.nodesep : 80;
    const ranksep = opts.ranksep != null ? opts.ranksep : 120;

    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: 'TB', nodesep, ranksep });
    g.setDefaultEdgeLabel(() => ({}));

    const nodeList = Array.isArray(nodes) ? nodes : [];
    const edgeList = Array.isArray(edges) ? edges : [];

    for (const n of nodeList) {
        g.setNode(n.id, { width: nodeWidth, height: nodeHeight });
    }
    for (const e of edgeList) {
        g.setEdge(e.source, e.target);
    }

    dagre.layout(g);

    const positioned = nodeList.map(n => {
        const dag = g.node(n.id);
        return {
            ...n,
            position: dag ? { x: dag.x - nodeWidth / 2, y: dag.y - nodeHeight / 2 } : (n.position || { x: 0, y: 0 }),
        };
    });

    return { nodes: positioned, edges: edgeList };
}

function summarize(node) {
    const t = node.type || 'bash';
    if (t === 'bash') return (node.script || '').split('\n')[0].slice(0, 60);
    if (t === 'skill') return node.skill || '';
    if (t === 'command') return node.command || '';
    if (t === 'prompt') return (node.prompt || node.prompt_file || '').slice(0, 60);
    if (t === 'gate') return node.condition || '';
    if (t === 'interrupt') return node.message || '';
    return '';
}

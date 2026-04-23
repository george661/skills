/**
 * dag-to-reactflow.js
 * Pure conversion utility: DAG node list ↔ React Flow nodes/edges
 * Uses Dagre for auto-layout (Sugiyama algorithm, same as layout.py)
 */

/**
 * Convert DAG to React Flow format with Dagre layout
 * @param {Object} dag - {nodes: [{id, type, config, depends_on?}]}
 * @returns {Object} - {nodes: [{id, type, data, position}], edges: [{id, source, target}]}
 */
function dagToReactFlow(dag) {
  if (!dag || !dag.nodes) {
    return { nodes: [], edges: [] };
  }

  // Build edges from depends_on
  const edges = [];
  const rfNodes = dag.nodes.map((node) => ({
    id: node.id,
    type: node.type || 'default',
    data: {
      label: node.config?.command || node.config?.skill || node.config?.cmd || node.id,
      ...node.config,
    },
    position: { x: 0, y: 0 }, // Placeholder; will be set by layout
  }));

  dag.nodes.forEach((node) => {
    if (node.depends_on && Array.isArray(node.depends_on)) {
      node.depends_on.forEach((depId) => {
        edges.push({
          id: `${depId}-${node.id}`,
          source: depId,
          target: node.id,
        });
      });
    }
  });

  // Apply Dagre layout
  return applyDagreLayout({ nodes: rfNodes, edges });
}

/**
 * Convert React Flow back to DAG format
 * @param {Object} rf - {nodes: [{id, type, data, position}], edges: [{source, target}]}
 * @returns {Object} - {nodes: [{id, type, config, depends_on}]}
 */
function reactFlowToDag(rf) {
  if (!rf || !rf.nodes) {
    return { nodes: [] };
  }

  // Build depends_on map from edges
  const dependsOnMap = {};
  (rf.edges || []).forEach((edge) => {
    if (!dependsOnMap[edge.target]) {
      dependsOnMap[edge.target] = [];
    }
    dependsOnMap[edge.target].push(edge.source);
  });

  const nodes = rf.nodes.map((node) => {
    const dagNode = {
      id: node.id,
      type: node.type,
      config: node.data || {},
    };
    if (dependsOnMap[node.id]) {
      dagNode.depends_on = dependsOnMap[node.id];
    }
    return dagNode;
  });

  return { nodes };
}

/**
 * Apply Dagre layout to React Flow nodes
 * @param {Object} rf - {nodes: [{id, type, data, position}], edges: [{source, target}]}
 * @returns {Object} - Same structure with updated positions
 */
function applyDagreLayout(rf) {
  // Simplified Dagre-style layout using topological sort (Kahn's algorithm)
  // React Flow and Dagre use 'TB' (top-to-bottom) rankdir by default
  
  const nodeMap = new Map(rf.nodes.map((n) => [n.id, n]));
  const inDegree = new Map();
  const adjList = new Map();
  
  // Initialize
  rf.nodes.forEach((node) => {
    inDegree.set(node.id, 0);
    adjList.set(node.id, []);
  });
  
  // Build adjacency list and in-degree
  rf.edges.forEach((edge) => {
    adjList.get(edge.source).push(edge.target);
    inDegree.set(edge.target, inDegree.get(edge.target) + 1);
  });
  
  // Topological sort (Kahn's algorithm)
  const queue = [];
  rf.nodes.forEach((node) => {
    if (inDegree.get(node.id) === 0) {
      queue.push(node.id);
    }
  });
  
  const layers = [];
  while (queue.length > 0) {
    const currentLayer = [...queue];
    queue.length = 0;
    layers.push(currentLayer);
    
    currentLayer.forEach((nodeId) => {
      (adjList.get(nodeId) || []).forEach((neighbor) => {
        const newInDegree = inDegree.get(neighbor) - 1;
        inDegree.set(neighbor, newInDegree);
        if (newInDegree === 0) {
          queue.push(neighbor);
        }
      });
    });
  }
  
  // Assign positions based on layers
  const nodeWidth = 180;
  const nodeHeight = 80;
  const horizontalSpacing = 50;
  const verticalSpacing = 100;
  
  layers.forEach((layer, layerIndex) => {
    const layerWidth = layer.length * nodeWidth + (layer.length - 1) * horizontalSpacing;
    layer.forEach((nodeId, indexInLayer) => {
      const node = nodeMap.get(nodeId);
      if (node) {
        node.position = {
          x: indexInLayer * (nodeWidth + horizontalSpacing) - layerWidth / 2,
          y: layerIndex * (nodeHeight + verticalSpacing),
        };
      }
    });
  });
  
  return rf;
}

// Export for tests and canvas
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { dagToReactFlow, reactFlowToDag, applyDagreLayout };
}

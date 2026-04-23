/**
 * validation-rules.js - Pure client-side validation rules for workflow DAGs
 * 
 * Each rule is a pure function that accepts a canvasState and returns ValidationIssue[].
 * 
 * @typedef {Object} ValidationIssue
 * @property {string} severity - "error" or "warning"
 * @property {string|null} node_id - The node ID causing the issue (null for workflow-level issues)
 * @property {string} code - Machine-readable error code (e.g., "required_field", "duplicate_id")
 * @property {string} message - Human-readable error message
 */

/**
 * Check that all nodes have required fields (id, type)
 * @param {Object} canvasState - Shape: { nodes: [{id, type, depends_on, ...}] }
 * @returns {ValidationIssue[]}
 */
function requiredFields(canvasState) {
  var issues = [];
  var nodes = canvasState.nodes || [];
  
  for (var i = 0; i < nodes.length; i++) {
    var node = nodes[i];
    
    if (!node.id || typeof node.id !== 'string' || node.id.trim() === '') {
      issues.push({
        severity: 'error',
        node_id: node.id || null,
        code: 'required_field',
        message: 'Node is missing required field: id'
      });
    }
    
    if (!node.type || typeof node.type !== 'string' || node.type.trim() === '') {
      issues.push({
        severity: 'error',
        node_id: node.id || null,
        code: 'required_field',
        message: 'Node "' + (node.id || 'unknown') + '" is missing required field: type'
      });
    }
  }
  
  return issues;
}

/**
 * Check that all node IDs are unique
 * @param {Object} canvasState
 * @returns {ValidationIssue[]}
 */
function uniqueNodeIds(canvasState) {
  var issues = [];
  var nodes = canvasState.nodes || [];
  var idCounts = {};
  
  // Count occurrences of each ID
  for (var i = 0; i < nodes.length; i++) {
    var node = nodes[i];
    if (node.id) {
      idCounts[node.id] = (idCounts[node.id] || 0) + 1;
    }
  }
  
  // Report duplicates
  for (var id in idCounts) {
    if (idCounts[id] > 1) {
      issues.push({
        severity: 'error',
        node_id: id,
        code: 'duplicate_id',
        message: 'Duplicate node ID: "' + id + '" appears ' + idCounts[id] + ' times'
      });
    }
  }
  
  return issues;
}

/**
 * Detect cycles in the dependency graph
 * @param {Object} canvasState
 * @returns {ValidationIssue[]}
 */
function detectCycles(canvasState) {
  var issues = [];
  var nodes = canvasState.nodes || [];
  
  // Build adjacency list
  var graph = {};
  var nodeIds = {};
  
  for (var i = 0; i < nodes.length; i++) {
    var node = nodes[i];
    if (node.id) {
      nodeIds[node.id] = true;
      graph[node.id] = node.depends_on || [];
    }
  }
  
  // DFS cycle detection with path tracking
  var visited = {};
  var recStack = {};
  
  function hasCycleDFS(nodeId, path) {
    if (recStack[nodeId]) {
      // Found a cycle - report it
      var cycleStart = path.indexOf(nodeId);
      var cyclePath = path.slice(cycleStart).concat([nodeId]);
      issues.push({
        severity: 'error',
        node_id: nodeId,
        code: 'cycle_detected',
        message: 'Cycle detected in dependency graph: ' + cyclePath.join(' → ')
      });
      return true;
    }
    
    if (visited[nodeId]) {
      return false;
    }
    
    visited[nodeId] = true;
    recStack[nodeId] = true;
    
    var deps = graph[nodeId] || [];
    for (var i = 0; i < deps.length; i++) {
      var dep = deps[i];
      if (nodeIds[dep]) {
        if (hasCycleDFS(dep, path.concat([nodeId]))) {
          return true;
        }
      }
    }
    
    recStack[nodeId] = false;
    return false;
  }
  
  // Check each node
  for (var nodeId in graph) {
    if (!visited[nodeId]) {
      hasCycleDFS(nodeId, []);
    }
  }
  
  return issues;
}

/**
 * Check that all depends_on references point to existing nodes
 * @param {Object} canvasState
 * @returns {ValidationIssue[]}
 */
function referenceIntegrity(canvasState) {
  var issues = [];
  var nodes = canvasState.nodes || [];
  
  // Build set of valid node IDs
  var validIds = {};
  for (var i = 0; i < nodes.length; i++) {
    var node = nodes[i];
    if (node.id) {
      validIds[node.id] = true;
    }
  }
  
  // Check each node's dependencies
  for (var i = 0; i < nodes.length; i++) {
    var node = nodes[i];
    var deps = node.depends_on || [];
    
    for (var j = 0; j < deps.length; j++) {
      var depId = deps[j];
      if (!validIds[depId]) {
        issues.push({
          severity: 'error',
          node_id: node.id || null,
          code: 'missing_dependency',
          message: 'Node "' + (node.id || 'unknown') + '" depends on non-existent node: "' + depId + '"'
        });
      }
    }
  }
  
  return issues;
}

// Export to global namespace for builder bundle to consume
if (typeof window !== 'undefined') {
  window.DAGDashboardValidation = window.DAGDashboardValidation || {};
  window.DAGDashboardValidation.rules = {
    requiredFields: requiredFields,
    uniqueNodeIds: uniqueNodeIds,
    detectCycles: detectCycles,
    referenceIntegrity: referenceIntegrity
  };
}

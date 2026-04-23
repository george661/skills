/**
 * workflow-canvas.js
 * React Flow canvas shell for workflow builder
 * Consumes window.__builderBundle injected by GW-5242 vendor bundle
 */

(function () {
  'use strict';

  /**
   * Initialize the workflow canvas
   * @param {HTMLElement} container - DOM element to mount canvas into
   * @param {Object} initialDag - {nodes: [{id, type, config, depends_on}]}
   */
  function initWorkflowCanvas(container, initialDag = { nodes: [] }) {
    if (!window.__builderBundle) {
      container.innerHTML = `
        <div style="
          display: flex;
          align-items: center;
          justify-content: center;
          height: 100%;
          background: var(--bg-primary);
          color: var(--text-secondary);
          font-size: 14px;
        ">
          Builder bundle not loaded. Feature flag disabled or bundle not available.
        </div>
      `;
      return;
    }

    const { React, ReactDOM, ReactFlow } = window.__builderBundle;
    
    // Load conversion utilities
    // In production, these are bundled together; for now they're separate modules
    const { dagToReactFlow, reactFlowToDag } = window.__dagToReactFlow || {};
    
    if (!dagToReactFlow || !reactFlowToDag) {
      console.error('dag-to-reactflow utilities not loaded');
      return;
    }

    const WorkflowCanvas = () => {
      const [rfState, setRfState] = React.useState(() => dagToReactFlow(initialDag));

      const onConnect = React.useCallback((connection) => {
        // Add edge when user connects two nodes
        const newEdge = {
          id: `${connection.source}-${connection.target}`,
          source: connection.source,
          target: connection.target,
        };
        setRfState((state) => ({
          ...state,
          edges: [...state.edges, newEdge],
        }));
      }, []);

      const onNodesDelete = React.useCallback((deletedNodes) => {
        // Handle Delete key to remove nodes
        const deletedIds = new Set(deletedNodes.map((n) => n.id));
        setRfState((state) => ({
          nodes: state.nodes.filter((n) => !deletedIds.has(n.id)),
          edges: state.edges.filter(
            (e) => !deletedIds.has(e.source) && !deletedIds.has(e.target)
          ),
        }));
      }, []);

      const onDrop = React.useCallback((event) => {
        event.preventDefault();
        const nodeType = event.dataTransfer.getData('application/reactflow-node-type');
        if (!nodeType) return;

        // Get drop position (simplified; React Flow provides helpers for this)
        const bounds = event.currentTarget.getBoundingClientRect();
        const position = {
          x: event.clientX - bounds.left,
          y: event.clientY - bounds.top,
        };

        const newNode = {
          id: `node-${Date.now()}`,
          type: nodeType,
          position,
          data: { label: `New ${nodeType}` },
        };

        setRfState((state) => ({
          ...state,
          nodes: [...state.nodes, newNode],
        }));
      }, []);

      const onDragOver = React.useCallback((event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
      }, []);

      // Listen for Delete/Backspace key
      React.useEffect(() => {
        const handleKeyDown = (event) => {
          if (event.key === 'Delete' || event.key === 'Backspace') {
            // React Flow handles this internally if nodes are selected
            // This is a fallback/hook for custom behavior
          }
        };
        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
      }, []);

      return React.createElement(ReactFlow, {
        nodes: rfState.nodes,
        edges: rfState.edges,
        onConnect,
        onNodesDelete,
        onDrop,
        onDragOver,
        style: { width: '100%', height: '100%' },
      });
    };

    // Render canvas
    const root = ReactDOM.createRoot(container);
    root.render(React.createElement(WorkflowCanvas));
  }

  // Expose utilities for tests
  if (typeof window !== 'undefined') {
    window.__testHooks = window.__testHooks || {};
    window.__testHooks.WorkflowCanvas = {
      initWorkflowCanvas,
      // Re-export converters for tests
      dagToReactFlow: window.__dagToReactFlow?.dagToReactFlow,
      reactFlowToDag: window.__dagToReactFlow?.reactFlowToDag,
    };
  }

  // Make init function globally available
  if (typeof window !== 'undefined') {
    window.initWorkflowCanvas = initWorkflowCanvas;
  }
})();

/**
 * Workflows page - list and detail views for workflow definitions
 */

async function renderWorkflowsList() {
    document.title = 'Workflows | DAG Dashboard';
    const mainContent = document.getElementById('main-content');
    
    mainContent.innerHTML = `
        <div class="workflows-list-container">
            <h1>Workflows</h1>
            <p class="loading">Loading workflows...</p>
        </div>
    `;

    try {
        const response = await fetch('/api/definitions');
        if (!response.ok) throw new Error('Failed to fetch workflows');
        
        const definitions = await response.json();
        
        // Group by source_dir
        const grouped = {};
        definitions.forEach(def => {
            if (!grouped[def.source_dir]) {
                grouped[def.source_dir] = [];
            }
            grouped[def.source_dir].push(def);
        });

        let html = '<h1>Workflows</h1>';
        
        if (definitions.length === 0) {
            html += '<p class="empty-state">No workflows found. Add YAML files to your workflows directory.</p>';
        } else {
            Object.entries(grouped).forEach(([sourceDir, workflows]) => {
                html += `<div class="workflow-group">
                    <h2 class="source-dir-header">${sourceDir}</h2>
                    <div class="workflow-cards">`;
                
                workflows.forEach(wf => {
                    const hasCollision = wf.collisions && wf.collisions.length > 0;
                    html += `
                        <div class="workflow-card ${hasCollision ? 'has-collision' : ''}">
                            <h3><a href="#/workflows/${wf.name}">${wf.name}</a></h3>
                            ${hasCollision ? `<span class="collision-badge" title="Also exists in: ${wf.collisions.join(', ')}">⚠️ Shadowed</span>` : ''}
                            <p class="workflow-path">${wf.path}</p>
                        </div>`;
                });
                
                html += `</div></div>`;
            });
        }

        mainContent.innerHTML = `<div class="workflows-list-container">${html}</div>`;
    } catch (error) {
        mainContent.innerHTML = `
            <div class="workflows-list-container">
                <h1>Workflows</h1>
                <p class="error">Error loading workflows: ${error.message}</p>
            </div>`;
    }
}

async function renderWorkflowDetail(name) {
    document.title = `${name} | DAG Dashboard`;
    const mainContent = document.getElementById('main-content');
    
    mainContent.innerHTML = `
        <div class="workflow-detail-container">
            <p class="loading">Loading workflow...</p>
        </div>
    `;

    try {
        const response = await fetch(`/api/definitions/${name}`);
        if (!response.ok) {
            if (response.status === 404) throw new Error('Workflow not found');
            throw new Error('Failed to fetch workflow');
        }
        
        const definition = await response.json();
        
        let html = `
            <div class="workflow-detail-header">
                <h1>${definition.name}</h1>
                <a href="#/workflows" class="back-link">← Back to workflows</a>
            </div>
            
            <section class="workflow-yaml">
                <h2>YAML Source</h2>
                <pre><code>${escapeHtml(definition.yaml_source)}</code></pre>
            </section>
            
            <section class="workflow-actions">
                <button onclick="triggerWorkflow('${name}')" class="button-primary">Run Workflow</button>
            </section>
        `;

        // Add DAG preview if parsed nodes exist
        if (definition.parsed && definition.parsed.nodes && definition.parsed.nodes.length > 0) {
            html += `
                <section class="workflow-dag">
                    <h2>DAG Preview</h2>
                    <div id="dag-preview-container"></div>
                </section>`;
        }

        mainContent.innerHTML = `<div class="workflow-detail-container">${html}</div>`;
        
        // Render DAG preview
        if (definition.parsed && definition.parsed.nodes) {
            renderDAGPreview(definition.parsed.nodes);
        }
        
    } catch (error) {
        mainContent.innerHTML = `
            <div class="workflow-detail-container">
                <h1>Error</h1>
                <p class="error">${error.message}</p>
                <a href="#/workflows" class="back-link">← Back to workflows</a>
            </div>`;
    }
}

function renderDAGPreview(nodes) {
    // Use existing DAGRenderer to show the graph
    const container = document.getElementById('dag-preview-container');
    if (!container || typeof DAGRenderer === 'undefined') return;
    
    // Transform nodes to the format DAGRenderer expects
    const nodeData = nodes.map(node => ({
        id: node.id,
        type: node.type || 'command',
        status: 'pending',  // Preview mode - no status
        depends_on: node.depends_on || [],
        ...node
    }));
    
    // Compute simple layout
    const layout = computeSimpleLayout(nodeData);
    
    // Render with DAGRenderer
    const renderer = new DAGRenderer(container, { interactive: false });
    renderer.render(layout.nodes, layout.edges);
}

function computeSimpleLayout(nodes) {
    // Simple layered layout - group by dependency depth
    const layers = [];
    const visited = new Set();
    const nodeMap = new Map(nodes.map(n => [n.id, n]));
    
    function getLayer(node) {
        if (visited.has(node.id)) return 0;
        visited.add(node.id);
        
        if (!node.depends_on || node.depends_on.length === 0) {
            return 0;
        }
        
        const depthLayers = node.depends_on.map(depId => {
            const depNode = nodeMap.get(depId);
            return depNode ? getLayer(depNode) + 1 : 0;
        });
        
        return Math.max(...depthLayers);
    }
    
    nodes.forEach(node => {
        const layer = getLayer(node);
        if (!layers[layer]) layers[layer] = [];
        layers[layer].push(node);
    });
    
    // Position nodes
    const layoutNodes = [];
    const nodeWidth = 180;
    const nodeHeight = 60;
    const layerGap = 150;
    const nodeGap = 20;
    
    layers.forEach((layerNodes, layerIdx) => {
        const layerY = layerIdx * layerGap;
        layerNodes.forEach((node, idx) => {
            const layerX = idx * (nodeWidth + nodeGap);
            layoutNodes.push({
                ...node,
                x: layerX,
                y: layerY,
                width: nodeWidth,
                height: nodeHeight
            });
        });
    });
    
    // Build edges
    const edges = [];
    nodes.forEach(node => {
        if (node.depends_on) {
            node.depends_on.forEach(depId => {
                edges.push({ from: depId, to: node.id });
            });
        }
    });
    
    return { nodes: layoutNodes, edges };
}

function triggerWorkflow(name) {
    // For now, just navigate to workflows page
    // In the future, could show a trigger form
    alert(`Trigger form for workflow "${name}" not yet implemented`);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Export for route registration
window.renderWorkflowsList = renderWorkflowsList;
window.renderWorkflowDetail = renderWorkflowDetail;

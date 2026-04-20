/**
 * DAG Dashboard - Checkpoint Browser
 * Provides UI for browsing workflow checkpoint runs
 */

/**
 * Render the list of workflows with checkpoints
 */
async function renderCheckpointWorkflows() {
    const container = document.getElementById('route-container');
    
    container.innerHTML = `
        <h2 style="margin-bottom: 1.5rem;">Checkpoint Workflows</h2>
        <div id="checkpoint-workflows-content">
            <div class="loading-spinner">Loading workflows...</div>
        </div>
    `;
    
    try {
        const response = await fetch('/api/checkpoints/workflows');
        const content = document.getElementById('checkpoint-workflows-content');
        
        if (!response.ok) {
            if (response.status === 404) {
                // Checkpoint prefix not configured
                content.innerHTML = `
                    <div class="empty-state" style="padding: 3rem 1rem;">
                        <div class="empty-state-icon">💾</div>
                        <div class="empty-state-text">
                            Checkpoint browsing is not configured.
                        </div>
                        <p style="color: var(--text-secondary); margin-top: 1rem; max-width: 500px; margin-left: auto; margin-right: auto;">
                            To enable checkpoint browsing, set the <code>DAG_DASHBOARD_CHECKPOINT_PREFIX</code> environment variable to the path where checkpoints are stored.
                        </p>
                    </div>
                `;
                return;
            }
            throw new Error(`Failed to load workflows: ${response.statusText}`);
        }
        
        const data = await response.json();
        const workflows = data.workflows || [];
        
        if (workflows.length === 0) {
            content.innerHTML = `
                <div class="empty-state" style="padding: 2rem 1rem;">
                    <div class="empty-state-icon">💾</div>
                    <div class="empty-state-text">No checkpoint workflows found</div>
                </div>
            `;
            return;
        }
        
        const workflowCards = workflows.map(wf => `
            <div class="workflow-card" style="cursor: pointer;" data-workflow="${escapeHtml(wf)}">
                <div class="workflow-title">${escapeHtml(wf)}</div>
                <div style="margin-top: 0.5rem; color: var(--text-secondary); font-size: 0.875rem;">
                    View checkpoint runs →
                </div>
            </div>
        `).join('');
        
        content.innerHTML = `
            <div class="workflow-list">
                ${workflowCards}
            </div>
        `;
        
        // Add click handlers
        document.querySelectorAll('[data-workflow]').forEach(card => {
            card.addEventListener('click', () => {
                const workflow = card.dataset.workflow;
                window.location.hash = `/checkpoints/${workflow}`;
            });
        });
        
    } catch (error) {
        console.error('Error loading checkpoint workflows:', error);
        const content = document.getElementById('checkpoint-workflows-content');
        content.innerHTML = `
            <div class="error-message">
                <strong>Error loading workflows:</strong> ${escapeHtml(error.message)}
            </div>
        `;
    }
}

/**
 * Render the list of checkpoint runs for a workflow
 */
async function renderCheckpointRuns(workflow) {
    const container = document.getElementById('route-container');
    
    // Parse query parameters for filters
    const hash = window.location.hash.slice(1);
    const urlParams = new URLSearchParams(hash.split('?')[1] || '');
    const currentStatus = urlParams.get('status') || '';
    const currentStartDate = urlParams.get('start_date') || '';
    const currentEndDate = urlParams.get('end_date') || '';
    
    container.innerHTML = `
        <div style="margin-bottom: 1rem;">
            <a href="#/checkpoints" style="color: var(--primary); text-decoration: none;">← Back to Workflows</a>
        </div>
        <h2 style="margin-bottom: 1.5rem;">Checkpoint Runs: ${escapeHtml(workflow)}</h2>
        
        <div class="history-filters">
            <div class="filter-group">
                <label for="checkpoint-status-filter">Status:</label>
                <select id="checkpoint-status-filter" class="filter-select">
                    <option value="">All</option>
                    <option value="running" ${currentStatus === 'running' ? 'selected' : ''}>Running</option>
                    <option value="completed" ${currentStatus === 'completed' ? 'selected' : ''}>Completed</option>
                    <option value="failed" ${currentStatus === 'failed' ? 'selected' : ''}>Failed</option>
                </select>
            </div>
            <div class="filter-group">
                <label for="checkpoint-start-date-filter">Start Date:</label>
                <input type="date" id="checkpoint-start-date-filter" class="filter-input" value="${escapeHtml(currentStartDate)}">
            </div>
            <div class="filter-group">
                <label for="checkpoint-end-date-filter">End Date:</label>
                <input type="date" id="checkpoint-end-date-filter" class="filter-input" value="${escapeHtml(currentEndDate)}">
            </div>
        </div>
        
        <div id="checkpoint-runs-content">
            <div class="loading-spinner">Loading checkpoint runs...</div>
        </div>
    `;
    
    // Add filter change handlers
    const applyFilters = () => {
        const status = document.getElementById('checkpoint-status-filter').value;
        const startDate = document.getElementById('checkpoint-start-date-filter').value;
        const endDate = document.getElementById('checkpoint-end-date-filter').value;
        
        const params = new URLSearchParams();
        if (status) params.set('status', status);
        if (startDate) params.set('start_date', startDate);
        if (endDate) params.set('end_date', endDate);
        
        const queryString = params.toString();
        window.location.hash = `/checkpoints/${workflow}${queryString ? '?' + queryString : ''}`;
    };
    
    document.getElementById('checkpoint-status-filter').addEventListener('change', applyFilters);
    document.getElementById('checkpoint-start-date-filter').addEventListener('change', applyFilters);
    document.getElementById('checkpoint-end-date-filter').addEventListener('change', applyFilters);
    
    try {
        // Build API query
        const apiParams = new URLSearchParams();
        if (currentStatus) apiParams.set('status', currentStatus);
        if (currentStartDate) apiParams.set('started_after', currentStartDate);
        if (currentEndDate) apiParams.set('started_before', currentEndDate);
        
        const response = await fetch(`/api/checkpoints/workflows/${encodeURIComponent(workflow)}/runs?${apiParams}`);
        const content = document.getElementById('checkpoint-runs-content');
        
        if (!response.ok) {
            throw new Error(`Failed to load runs: ${response.statusText}`);
        }
        
        const data = await response.json();
        const runs = data.runs || [];
        
        if (runs.length === 0) {
            content.innerHTML = `
                <div class="empty-state" style="padding: 2rem 1rem;">
                    <div class="empty-state-icon">💾</div>
                    <div class="empty-state-text">No checkpoint runs found</div>
                </div>
            `;
            return;
        }
        
        // Build table
        const rows = runs.map(run => {
            const startTime = run.started_at || run.run_id;
            const status = run.status || 'unknown';
            return `
                <tr class="history-row" data-run-id="${escapeHtml(run.run_id)}" style="cursor: pointer;">
                    <td class="history-cell">${escapeHtml(run.run_id)}</td>
                    <td class="history-cell"><span class="workflow-status ${escapeHtml(status)}">${escapeHtml(status)}</span></td>
                    <td class="history-cell">${escapeHtml(startTime)}</td>
                    <td class="history-cell">${run.node_count || 0} nodes</td>
                </tr>
            `;
        }).join('');
        
        content.innerHTML = `
            <div class="history-table-wrapper">
                <table class="history-table">
                    <thead>
                        <tr>
                            <th class="history-header">Run ID</th>
                            <th class="history-header">Status</th>
                            <th class="history-header">Started At</th>
                            <th class="history-header">Nodes</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows}
                    </tbody>
                </table>
            </div>
        `;
        
        // Add click handlers
        document.querySelectorAll('[data-run-id]').forEach(row => {
            row.addEventListener('click', () => {
                const runId = row.dataset.runId;
                window.location.hash = `/checkpoints/${workflow}/${runId}`;
            });
        });
        
    } catch (error) {
        console.error('Error loading checkpoint runs:', error);
        const content = document.getElementById('checkpoint-runs-content');
        content.innerHTML = `
            <div class="error-message">
                <strong>Error loading runs:</strong> ${escapeHtml(error.message)}
            </div>
        `;
    }
}

/**
 * Render detailed view of a single checkpoint run
 */
async function renderCheckpointRunDetail(workflow, runId) {
    const container = document.getElementById('route-container');
    
    container.innerHTML = `
        <div style="margin-bottom: 1rem;">
            <a href="#/checkpoints/${escapeHtml(workflow)}" style="color: var(--primary); text-decoration: none;">← Back to Runs</a>
        </div>
        <h2 style="margin-bottom: 1rem;">Checkpoint Run Detail</h2>
        <div style="margin-bottom: 1.5rem;">
            <strong>Workflow:</strong> ${escapeHtml(workflow)}<br>
            <strong>Run ID:</strong> ${escapeHtml(runId)}
        </div>
        
        <div style="margin-bottom: 1rem;">
            <button id="replay-btn" class="btn btn-primary">
                🔄 Replay from Checkpoint
            </button>
            <button id="compare-btn" class="btn btn-secondary" style="margin-left: 0.5rem;">
                📊 Compare with Another Run
            </button>
        </div>
        
        <div id="checkpoint-detail-content">
            <div class="loading-spinner">Loading checkpoint details...</div>
        </div>
    `;
    
    // Add replay button handler
    document.getElementById('replay-btn').addEventListener('click', () => {
        if (window.showReplayModal) {
            window.showReplayModal(workflow, runId);
        }
    });
    
    // Add compare button handler (will be implemented later)
    document.getElementById('compare-btn').addEventListener('click', () => {
        const runIdB = prompt('Enter the Run ID to compare with:');
        if (runIdB) {
            window.location.hash = `/checkpoints/compare/${workflow}/${runId}/${runIdB}`;
        }
    });
    
    try {
        const response = await fetch(`/api/checkpoints/workflows/${encodeURIComponent(workflow)}/runs/${encodeURIComponent(runId)}`);
        const content = document.getElementById('checkpoint-detail-content');
        
        if (!response.ok) {
            throw new Error(`Failed to load run detail: ${response.statusText}`);
        }
        
        const data = await response.json();
        
        // Display metadata
        let metadataHTML = '<h3 style="margin-bottom: 1rem;">Run Metadata</h3>';
        if (data.metadata) {
            metadataHTML += '<div class="metadata-table">';
            for (const [key, value] of Object.entries(data.metadata)) {
                metadataHTML += `
                    <div class="metadata-row">
                        <div class="metadata-key">${escapeHtml(key)}:</div>
                        <div class="metadata-value">${escapeHtml(String(value))}</div>
                    </div>
                `;
            }
            metadataHTML += '</div>';
        } else {
            metadataHTML += '<p style="color: var(--text-secondary);">No metadata available</p>';
        }
        
        // Display nodes
        const nodes = data.nodes || [];
        let nodesHTML = '<h3 style="margin-top: 2rem; margin-bottom: 1rem;">Node Checkpoints</h3>';
        
        if (nodes.length === 0) {
            nodesHTML += '<p style="color: var(--text-secondary);">No node checkpoints found</p>';
        } else {
            const nodeRows = nodes.map(node => `
                <tr class="history-row node-row" data-node-id="${escapeHtml(node.node_id)}" style="cursor: pointer;">
                    <td class="history-cell">${escapeHtml(node.node_id)}</td>
                    <td class="history-cell"><span class="workflow-status ${escapeHtml(node.status || 'unknown')}">${escapeHtml(node.status || 'unknown')}</span></td>
                    <td class="history-cell">${escapeHtml(node.timestamp || 'N/A')}</td>
                </tr>
                <tr class="node-detail-row" id="node-detail-${escapeHtml(node.node_id)}" style="display: none;">
                    <td colspan="3" class="node-detail-cell">
                        <div class="node-detail-content">
                            <h4>Full Checkpoint Data:</h4>
                            <pre style="background: var(--bg-secondary); padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.875rem;">${escapeHtml(JSON.stringify(node, null, 2))}</pre>
                        </div>
                    </td>
                </tr>
            `).join('');
            
            nodesHTML += `
                <div class="history-table-wrapper">
                    <table class="history-table">
                        <thead>
                            <tr>
                                <th class="history-header">Node ID</th>
                                <th class="history-header">Status</th>
                                <th class="history-header">Timestamp</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${nodeRows}
                        </tbody>
                    </table>
                </div>
            `;
        }
        
        content.innerHTML = metadataHTML + nodesHTML;
        
        // Add click handlers for node rows
        document.querySelectorAll('.node-row').forEach(row => {
            row.addEventListener('click', () => {
                const nodeId = row.dataset.nodeId;
                const detailRow = document.getElementById(`node-detail-${nodeId}`);
                if (detailRow) {
                    const isVisible = detailRow.style.display !== 'none';
                    detailRow.style.display = isVisible ? 'none' : 'table-row';
                }
            });
        });
        
    } catch (error) {
        console.error('Error loading checkpoint run detail:', error);
        const content = document.getElementById('checkpoint-detail-content');
        content.innerHTML = `
            <div class="error-message">
                <strong>Error loading run detail:</strong> ${escapeHtml(error.message)}
            </div>
        `;
    }
}

/**
 * Render comparison view between two checkpoint runs
 */
async function renderCheckpointCompare(workflow, runIdA, runIdB) {
    const container = document.getElementById('route-container');
    
    container.innerHTML = `
        <div style="margin-bottom: 1rem;">
            <a href="#/checkpoints/${escapeHtml(workflow)}" style="color: var(--primary); text-decoration: none;">← Back to Runs</a>
        </div>
        <h2 style="margin-bottom: 1rem;">Compare Checkpoint Runs</h2>
        <div style="margin-bottom: 1.5rem;">
            <strong>Workflow:</strong> ${escapeHtml(workflow)}<br>
            <strong>Run A:</strong> ${escapeHtml(runIdA)}<br>
            <strong>Run B:</strong> ${escapeHtml(runIdB)}
        </div>
        
        <div id="checkpoint-compare-content">
            <div class="loading-spinner">Loading comparison...</div>
        </div>
    `;
    
    try {
        // Fetch both runs in parallel
        const [responseA, responseB] = await Promise.all([
            fetch(`/api/checkpoints/workflows/${encodeURIComponent(workflow)}/runs/${encodeURIComponent(runIdA)}`),
            fetch(`/api/checkpoints/workflows/${encodeURIComponent(workflow)}/runs/${encodeURIComponent(runIdB)}`)
        ]);
        
        if (!responseA.ok || !responseB.ok) {
            throw new Error('Failed to load one or both runs');
        }
        
        const [dataA, dataB] = await Promise.all([
            responseA.json(),
            responseB.json()
        ]);
        
        const nodesA = dataA.nodes || [];
        const nodesB = dataB.nodes || [];
        
        // Create node maps
        const nodeMapA = new Map(nodesA.map(n => [n.node_id, n]));
        const nodeMapB = new Map(nodesB.map(n => [n.node_id, n]));
        
        // Get all unique node IDs
        const allNodeIds = new Set([...nodeMapA.keys(), ...nodeMapB.keys()]);
        
        // Build comparison rows
        const comparisonRows = Array.from(allNodeIds).sort().map(nodeId => {
            const nodeA = nodeMapA.get(nodeId);
            const nodeB = nodeMapB.get(nodeId);
            
            let rowClass = '';
            if (!nodeA) rowClass = 'diff-row-added';
            else if (!nodeB) rowClass = 'diff-row-removed';
            else if (JSON.stringify(nodeA) !== JSON.stringify(nodeB)) rowClass = 'diff-row-changed';
            
            const statusA = nodeA ? `<span class="workflow-status ${escapeHtml(nodeA.status || 'unknown')}">${escapeHtml(nodeA.status || 'unknown')}</span>` : '<span style="color: var(--text-secondary);">—</span>';
            const statusB = nodeB ? `<span class="workflow-status ${escapeHtml(nodeB.status || 'unknown')}">${escapeHtml(nodeB.status || 'unknown')}</span>` : '<span style="color: var(--text-secondary);">—</span>';
            
            return `
                <tr class="history-row ${rowClass}">
                    <td class="history-cell">${escapeHtml(nodeId)}</td>
                    <td class="history-cell">${statusA}</td>
                    <td class="history-cell">${statusB}</td>
                </tr>
            `;
        }).join('');
        
        const content = document.getElementById('checkpoint-compare-content');
        content.innerHTML = `
            <div class="diff-legend" style="margin-bottom: 1rem; display: flex; gap: 1rem; flex-wrap: wrap;">
                <div><span class="diff-indicator diff-row-added" style="display: inline-block; width: 12px; height: 12px; border-radius: 2px;"></span> Added in Run B</div>
                <div><span class="diff-indicator diff-row-removed" style="display: inline-block; width: 12px; height: 12px; border-radius: 2px;"></span> Removed in Run B</div>
                <div><span class="diff-indicator diff-row-changed" style="display: inline-block; width: 12px; height: 12px; border-radius: 2px;"></span> Changed between runs</div>
            </div>
            
            <div class="history-table-wrapper">
                <table class="history-table">
                    <thead>
                        <tr>
                            <th class="history-header">Node ID</th>
                            <th class="history-header">Run A Status</th>
                            <th class="history-header">Run B Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${comparisonRows}
                    </tbody>
                </table>
            </div>
        `;
        
    } catch (error) {
        console.error('Error loading comparison:', error);
        const content = document.getElementById('checkpoint-compare-content');
        content.innerHTML = `
            <div class="error-message">
                <strong>Error loading comparison:</strong> ${escapeHtml(error.message)}
            </div>
        `;
    }
}

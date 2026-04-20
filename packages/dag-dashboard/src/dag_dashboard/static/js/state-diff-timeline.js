/**
 * State Diff Timeline - Visualize channel state changes per node execution
 */

/**
 * Render state diff timeline for a workflow run
 * @param {HTMLElement} container - Container to render timeline into
 * @param {string} runId - Workflow run ID
 */
async function renderStateDiffTimeline(container, runId) {
    if (!container || !runId) {
        console.warn('renderStateDiffTimeline: missing container or runId');
        return;
    }

    try {
        const response = await fetch(`/api/workflows/${runId}/state-diff-timeline`);
        
        if (!response.ok) {
            if (response.status === 404) {
                container.innerHTML = '<p class="timeline-empty">Workflow run not found</p>';
                return;
            }
            throw new Error(`HTTP ${response.status}`);
        }

        const timeline = await response.json();
        
        if (!timeline || timeline.length === 0) {
            container.innerHTML = '<p class="timeline-empty">No state changes yet</p>';
            return;
        }

        // Render timeline
        const timelineHtml = timeline.map(nodeEntry => renderNodeEntry(nodeEntry)).join('');
        container.innerHTML = `<div class="state-diff-timeline">${timelineHtml}</div>`;

        // Wire expand/collapse handlers
        container.querySelectorAll('.diff-row').forEach(row => {
            row.addEventListener('click', () => {
                const valuesDiv = row.querySelector('.diff-values');
                if (valuesDiv) {
                    valuesDiv.classList.toggle('expanded');
                }
            });
        });

    } catch (error) {
        console.error('Error fetching state diff timeline:', error);
        container.innerHTML = `<p class="timeline-error">Error loading timeline: ${escapeHtml(error.message)}</p>`;
    }
}

/**
 * Render a single node entry in the timeline
 * @param {Object} nodeEntry - Node state diff entry
 * @returns {string} HTML string
 */
function renderNodeEntry(nodeEntry) {
    const { node_name, node_id, started_at, finished_at, changes } = nodeEntry;
    
    // Format timestamps
    const startTime = started_at ? new Date(started_at).toLocaleTimeString() : 'N/A';
    const endTime = finished_at ? new Date(finished_at).toLocaleTimeString() : 'N/A';
    
    // Render changes
    const changesHtml = changes.map(change => renderChange(change)).join('');
    
    return `
        <div class="diff-node">
            <div class="diff-node-header">
                <strong>${escapeHtml(node_name)}</strong>
                <span class="diff-node-time">${startTime} - ${endTime}</span>
            </div>
            <div class="diff-changes">
                ${changesHtml || '<p class="no-changes">No changes</p>'}
            </div>
        </div>
    `;
}

/**
 * Render a single change entry
 * @param {Object} change - Change object with key, change_type, before, after
 * @returns {string} HTML string
 */
function renderChange(change) {
    const { key, change_type, before, after } = change;
    
    // Choose CSS class based on change type
    const cssClass = `diff-${change_type}`;
    
    // Icon for change type
    const icon = {
        added: '➕',
        changed: '✏️',
        removed: '➖'
    }[change_type] || '•';
    
    // Format values as JSON
    const beforeJson = before !== null ? JSON.stringify(before, null, 2) : 'null';
    const afterJson = after !== null ? JSON.stringify(after, null, 2) : 'null';
    
    return `
        <div class="diff-row ${cssClass}">
            <div class="diff-row-header">
                <span class="diff-icon">${icon}</span>
                <span class="diff-key">${escapeHtml(key)}</span>
                <span class="diff-type">${escapeHtml(change_type)}</span>
                <span class="diff-chevron">▼</span>
            </div>
            <div class="diff-values">
                <div class="diff-value-pair">
                    <div class="diff-value-label">Before:</div>
                    <pre class="diff-value-content">${escapeHtml(beforeJson)}</pre>
                </div>
                <div class="diff-value-pair">
                    <div class="diff-value-label">After:</div>
                    <pre class="diff-value-content">${escapeHtml(afterJson)}</pre>
                </div>
            </div>
        </div>
    `;
}

// Export for use in app.js
if (typeof window !== 'undefined') {
    window.renderStateDiffTimeline = renderStateDiffTimeline;
}

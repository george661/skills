/**
 * DAG Dashboard - Replay Form Modal
 * Provides UI for replaying workflows from checkpoints
 */

/**
 * Show the replay modal for a given workflow and run
 */
window.showReplayModal = async function(workflow, runId) {
    // Create modal overlay if it doesn't exist
    let modal = document.getElementById('replay-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'replay-modal';
        modal.className = 'modal-overlay';
        document.body.appendChild(modal);
    }
    
    // Fetch run details to get node list
    let nodes = [];
    try {
        const response = await fetch(`/api/checkpoints/workflows/${encodeURIComponent(workflow)}/runs/${encodeURIComponent(runId)}`);
        if (response.ok) {
            const data = await response.json();
            nodes = (data.nodes || []).map(n => n.node_id);
        }
    } catch (error) {
        console.error('Error loading nodes:', error);
    }
    
    // Build node options
    const nodeOptions = nodes.length > 0
        ? nodes.map(nodeId => `<option value="${escapeHtml(nodeId)}">${escapeHtml(nodeId)}</option>`).join('')
        : '<option value="">No nodes available</option>';
    
    // Render modal content
    modal.innerHTML = `
        <div class="modal-content">
            <div class="modal-header">
                <h3>Replay from Checkpoint</h3>
                <button class="modal-close" id="replay-modal-close">&times;</button>
            </div>
            <div class="modal-body">
                <form id="replay-form">
                    <div class="form-group">
                        <label for="replay-from-node">From Node: <span style="color: red;">*</span></label>
                        <select id="replay-from-node" class="form-control" required>
                            <option value="">Select a node...</option>
                            ${nodeOptions}
                        </select>
                    </div>

                    <div class="form-group">
                        <label for="replay-workflow-path">Workflow Path: <span style="color: red;">*</span></label>
                        <input type="text" id="replay-workflow-path" class="form-control" placeholder="/absolute/path/to/workflow.yaml" required>
                    </div>

                    <div class="form-group">
                        <label>State Overrides:</label>
                        <div id="override-rows">
                            <!-- Dynamic override rows will be added here -->
                        </div>
                        <button type="button" id="add-override-btn" class="btn btn-secondary btn-sm">
                            + Add Override
                        </button>
                    </div>
                    
                    <div class="form-group" style="margin-top: 1.5rem;">
                        <button type="submit" class="btn btn-primary">Start Replay</button>
                        <button type="button" class="btn btn-secondary" id="replay-cancel-btn">Cancel</button>
                    </div>
                    
                    <div id="replay-error" class="error-message" style="display: none; margin-top: 1rem;"></div>
                </form>
            </div>
        </div>
    `;
    
    // Show modal
    modal.style.display = 'flex';
    
    // Add event handlers
    document.getElementById('replay-modal-close').addEventListener('click', closeReplayModal);
    document.getElementById('replay-cancel-btn').addEventListener('click', closeReplayModal);
    
    // Override management
    let overrideCount = 0;
    const overrideContainer = document.getElementById('override-rows');
    
    function addOverrideRow() {
        overrideCount++;
        const row = document.createElement('div');
        row.className = 'override-row';
        row.dataset.overrideId = overrideCount;
        row.innerHTML = `
            <input type="text" class="form-control override-key" placeholder="Key" style="flex: 1;">
            <input type="text" class="form-control override-value" placeholder="Value" style="flex: 1; margin-left: 0.5rem;">
            <button type="button" class="btn btn-danger btn-sm remove-override-btn" style="margin-left: 0.5rem;">×</button>
        `;
        
        row.querySelector('.remove-override-btn').addEventListener('click', () => {
            row.remove();
        });
        
        overrideContainer.appendChild(row);
    }
    
    document.getElementById('add-override-btn').addEventListener('click', addOverrideRow);
    
    // Form submission
    document.getElementById('replay-form').addEventListener('submit', async (e) => {
        e.preventDefault();

        const fromNode = document.getElementById('replay-from-node').value;
        const workflowPath = document.getElementById('replay-workflow-path').value.trim();
        const errorDiv = document.getElementById('replay-error');

        // Client-side validation
        if (!fromNode) {
            errorDiv.textContent = 'Please select a node to replay from.';
            errorDiv.style.display = 'block';
            return;
        }

        if (!workflowPath) {
            errorDiv.textContent = 'Please provide a workflow path.';
            errorDiv.style.display = 'block';
            return;
        }

        // Collect overrides
        const overrides = {};
        document.querySelectorAll('.override-row').forEach(row => {
            const key = row.querySelector('.override-key').value.trim();
            const value = row.querySelector('.override-value').value.trim();
            if (key) {
                overrides[key] = value;
            }
        });

        // Build request payload
        const payload = {
            from_node: fromNode,
            workflow_path: workflowPath
        };
        if (Object.keys(overrides).length > 0) {
            payload.overrides = overrides;
        }
        
        // Submit replay request
        try {
            errorDiv.style.display = 'none';
            const response = await fetch(
                `/api/checkpoints/workflows/${encodeURIComponent(workflow)}/runs/${encodeURIComponent(runId)}/replay`,
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(payload)
                }
            );
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.error || `Replay failed: ${response.statusText}`);
            }
            
            const result = await response.json();
            
            // Close modal
            closeReplayModal();
            
            // Show success toast
            showToast('Replay started successfully!', 'success');

            // Navigate to the new run if we have a new_run_id
            if (result.new_run_id) {
                setTimeout(() => {
                    window.location.hash = `/checkpoints/workflow/${result.new_run_id}`;
                }, 1000);
            }
            
        } catch (error) {
            console.error('Error submitting replay:', error);
            errorDiv.textContent = `Error: ${escapeHtml(error.message)}`;
            errorDiv.style.display = 'block';
        }
    });
    
    // Close modal on overlay click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeReplayModal();
        }
    });
};

/**
 * Close the replay modal
 */
function closeReplayModal() {
    const modal = document.getElementById('replay-modal');
    if (modal) {
        modal.style.display = 'none';
    }
}

/**
 * Show a toast notification
 */
function showToast(message, type = 'info') {
    // Create toast if it doesn't exist
    let toast = document.getElementById('toast-notification');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'toast-notification';
        toast.className = 'toast';
        document.body.appendChild(toast);
    }
    
    toast.textContent = message;
    toast.className = `toast toast-${type} toast-show`;
    
    // Auto-hide after 3 seconds
    setTimeout(() => {
        toast.classList.remove('toast-show');
    }, 3000);
}

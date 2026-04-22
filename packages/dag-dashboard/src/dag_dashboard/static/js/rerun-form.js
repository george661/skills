/**
 * DAG Dashboard - Rerun Form Modal
 * Provides UI for re-running workflows with optionally modified inputs
 */

/**
 * Show the rerun modal for a given run
 */
window.showRerunModal = async function(runId) {
    // Create modal overlay if it doesn't exist
    let modal = document.getElementById('rerun-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'rerun-modal';
        modal.className = 'modal-overlay';
        document.body.appendChild(modal);
    }
    
    // Fetch run details to get prior inputs
    let priorInputs = {};
    try {
        const response = await fetch(`/api/workflows/${encodeURIComponent(runId)}`);
        if (response.ok) {
            const data = await response.json();
            if (data.run && data.run.inputs) {
                priorInputs = data.run.inputs;
            }
        }
    } catch (error) {
        console.error('Error loading run:', error);
    }
    
    // Build input fields from prior inputs
    const inputFields = Object.keys(priorInputs).length > 0
        ? Object.entries(priorInputs).map(([key, value]) => {
            const valueStr = typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
            return `
                <div class="form-group">
                    <label for="rerun-input-${escapeHtml(key)}">${escapeHtml(key)}:</label>
                    <textarea id="rerun-input-${escapeHtml(key)}" 
                              class="form-control rerun-input-field" 
                              data-key="${escapeHtml(key)}"
                              rows="3">${escapeHtml(valueStr)}</textarea>
                </div>
            `;
          }).join('')
        : '<p>No inputs from prior run.</p>';
    
    // Render modal content
    modal.innerHTML = `
        <div class="modal-content">
            <div class="modal-header">
                <h3>Re-run Workflow</h3>
                <button class="modal-close" id="rerun-modal-close">&times;</button>
            </div>
            <div class="modal-body">
                <form id="rerun-form">
                    <p style="margin-bottom: 1rem; color: #666;">
                        Modify inputs below and click "Re-run" to start a new execution with the updated values.
                    </p>
                    
                    ${inputFields}
                    
                    <div class="form-group" style="margin-top: 1.5rem;">
                        <button type="submit" class="btn btn-primary">Re-run</button>
                        <button type="button" class="btn btn-secondary" id="rerun-cancel-btn">Cancel</button>
                    </div>
                    
                    <div id="rerun-error" class="error-message" style="display: none; margin-top: 1rem;"></div>
                </form>
            </div>
        </div>
    `;
    
    // Show modal
    modal.style.display = 'flex';
    
    // Set up event handlers
    const closeBtn = document.getElementById('rerun-modal-close');
    const cancelBtn = document.getElementById('rerun-cancel-btn');
    const form = document.getElementById('rerun-form');
    const errorDiv = document.getElementById('rerun-error');
    
    function closeModal() {
        modal.style.display = 'none';
    }
    
    closeBtn.addEventListener('click', closeModal);
    cancelBtn.addEventListener('click', closeModal);
    
    // Close modal on overlay click
    modal.addEventListener('click', function(e) {
        if (e.target === modal) {
            closeModal();
        }
    });
    
    // Handle form submission
    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        errorDiv.style.display = 'none';

        // Show confirmation dialog
        const confirmed = await window.showConfirmDialog({
            title: 'Confirm Re-run',
            message: `Re-run workflow ${runId} with the modified inputs? A new execution will start.`,
            confirmLabel: 'Re-run',
            cancelLabel: 'Cancel',
            confirmTone: 'primary'
        });

        if (!confirmed) {
            errorDiv.style.display = 'none';
            return;
        }

        // Collect inputs from form fields
        const inputs = {};
        const inputElements = document.querySelectorAll('.rerun-input-field');
        
        for (const element of inputElements) {
            const key = element.dataset.key;
            const value = element.value.trim();
            
            // Try to parse as JSON if it looks like JSON
            if (value.startsWith('{') || value.startsWith('[')) {
                try {
                    inputs[key] = JSON.parse(value);
                } catch (e) {
                    inputs[key] = value;
                }
            } else if (!isNaN(value) && value !== '') {
                inputs[key] = Number(value);
            } else {
                inputs[key] = value;
            }
        }
        
        // Submit rerun request
        try {
            const response = await fetch(`/api/workflows/${encodeURIComponent(runId)}/rerun`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ inputs })
            });
            
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || `HTTP ${response.status}`);
            }
            
            const result = await response.json();
            
            // Show success toast
            if (window.showToast) {
                window.showToast(`Re-run started: ${result.run_id}`, 'success');
            }
            
            // Close modal and navigate to new run
            closeModal();
            window.location.hash = `#/workflow/${result.run_id}`;
            
        } catch (error) {
            console.error('Rerun error:', error);
            errorDiv.textContent = `Error: ${error.message}`;
            errorDiv.style.display = 'block';
        }
    });
};

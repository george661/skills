/**
 * CancelButton - Cancel workflow button with confirmation dialog
 * 
 * Renders a Cancel button on running workflows, uses ConfirmDialog for confirmation,
 * POSTs to /api/workflows/{run_id}/cancel on confirm.
 */

window.renderCancelButton = function(container, runId, currentStatus) {
    // Only show button for running workflows
    if (currentStatus !== 'running') {
        // Remove button if it exists
        if (container) {
            container.innerHTML = '';
        }
        return;
    }
    
    if (!container) {
        console.error('CancelButton: container element is required');
        return;
    }
    
    // Create cancel button
    const button = document.createElement('button');
    button.className = 'btn btn-danger cancel-run-btn';
    button.textContent = 'Cancel Run';
    button.setAttribute('data-run-id', runId);
    
    // Click handler
    button.addEventListener('click', async function() {
        // Disable button during operation
        button.disabled = true;
        
        // Show confirmation dialog
        const confirmed = await window.showConfirmDialog({
            title: 'Cancel Run?',
            message: `Cancel run ${runId}? Running nodes will be terminated.`,
            confirmLabel: 'Cancel Run',
            cancelLabel: 'Keep Running',
            confirmTone: 'danger'
        });
        
        if (!confirmed) {
            // User dismissed or clicked Keep Running
            button.disabled = false;
            return;
        }
        
        // User confirmed - send cancel request
        try {
            const response = await fetch(`/api/workflows/${runId}/cancel`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            
            if (response.ok) {
                // Success
                window.showToast('Cancel requested', 'success');
                // Leave button disabled - SSE will update status and hide button
                
                // Safety timeout: if no SSE update after 30 seconds, re-enable with info
                setTimeout(() => {
                    if (button && !button.offsetParent) return; // Button was removed
                    if (button.disabled) {
                        button.disabled = false;
                        window.showToast('Cancel request sent (waiting for executor)', 'info');
                    }
                }, 30000);
            } else {
                // Error response
                const errorData = await response.json().catch(() => ({}));
                const errorMsg = errorData.message || `Failed to cancel run (${response.status})`;
                window.showToast(errorMsg, 'error');
                button.disabled = false;
            }
        } catch (error) {
            console.error('Error canceling run:', error);
            window.showToast('Network error while canceling run', 'error');
            button.disabled = false;
        }
    });
    
    // Insert button into container
    container.innerHTML = '';
    container.appendChild(button);
};

/**
 * Hide/remove cancel button from container
 */
window.hideCancelButton = function(container) {
    if (container) {
        container.innerHTML = '';
    }
};

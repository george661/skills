/**
 * RetryButton - Retry workflow button with confirmation dialog
 * 
 * Renders a Retry button on failed workflows, uses ConfirmDialog for confirmation,
 * POSTs to /api/workflows/{run_id}/retry on confirm.
 */

window.renderRetryButton = function(container, runId, currentStatus) {
    // Only show button for failed workflows
    if (currentStatus !== 'failed') {
        // Remove button if it exists
        if (container) {
            container.innerHTML = '';
        }
        return;
    }
    
    if (!container) {
        console.error('RetryButton: container element is required');
        return;
    }
    
    // Create retry button
    const button = document.createElement('button');
    button.className = 'btn btn-primary retry-run-btn';
    button.textContent = 'Retry Run';
    button.setAttribute('data-run-id', runId);
    
    // Click handler
    button.addEventListener('click', async function() {
        // Disable button during operation
        button.disabled = true;
        
        // Show confirmation dialog
        const confirmed = await window.showConfirmDialog({
            title: 'Retry Run?',
            message: `Retry run ${runId}? Failed nodes will re-execute; completed nodes will be skipped.`,
            confirmLabel: 'Retry Run',
            cancelLabel: 'Cancel',
            confirmTone: 'primary'
        });
        
        if (!confirmed) {
            // User dismissed or clicked Cancel
            button.disabled = false;
            return;
        }
        
        // User confirmed - send retry request
        try {
            const response = await fetch(`/api/workflows/${runId}/retry`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            
            if (response.ok) {
                // Success
                window.showToast('Retry started', 'success');
                // Hide button - SSE will update status when new workflow_started event arrives
                if (container) {
                    container.innerHTML = '';
                }
                
            } else {
                // Error response
                const errorData = await response.json().catch(() => ({}));
                const errorMsg = errorData.detail || errorData.message || `Failed to retry run (${response.status})`;
                window.showToast(errorMsg, 'error');
                button.disabled = false;
            }
        } catch (error) {
            console.error('Error retrying run:', error);
            window.showToast('Network error while retrying run', 'error');
            button.disabled = false;
        }
    });
    
    // Insert button into container
    container.innerHTML = '';
    container.appendChild(button);
};

/**
 * Hide/remove retry button from container
 */
window.hideRetryButton = function(container) {
    if (container) {
        container.innerHTML = '';
    }
};

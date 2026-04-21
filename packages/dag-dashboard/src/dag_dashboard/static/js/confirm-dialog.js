/**
 * ConfirmDialog - Reusable modal confirmation dialog component
 * 
 * Provides a focus-trapped modal with Cancel/Confirm buttons.
 * Supports Escape to close, overlay click to dismiss.
 * Returns Promise<boolean> - true for confirm, false for cancel/dismiss.
 */

window.showConfirmDialog = function({
    title = 'Confirm Action',
    message = 'Are you sure?',
    confirmLabel = 'Confirm',
    cancelLabel = 'Cancel',
    confirmTone = 'danger'  // 'danger' or 'primary'
}) {
    return new Promise((resolve) => {
        // Store current active element to restore focus later
        const previousActiveElement = document.activeElement;
        
        // Create modal overlay
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        
        // Create modal content
        const modal = document.createElement('div');
        modal.className = 'modal-content';
        
        modal.innerHTML = `
            <div class="modal-header">
                <h2>${escapeHtml(title)}</h2>
            </div>
            <div class="modal-body">
                <p>${escapeHtml(message)}</p>
            </div>
            <div class="modal-actions">
                <button class="btn btn-secondary cancel-btn">${escapeHtml(cancelLabel)}</button>
                <button class="btn btn-${confirmTone} confirm-btn">${escapeHtml(confirmLabel)}</button>
            </div>
        `;
        
        overlay.appendChild(modal);
        document.body.appendChild(overlay);
        
        // Get button elements
        const cancelBtn = modal.querySelector('.cancel-btn');
        const confirmBtn = modal.querySelector('.confirm-btn');
        const focusableElements = [cancelBtn, confirmBtn];
        
        // Focus the safer Cancel button by default (for destructive actions)
        cancelBtn.focus();
        
        // Close dialog function
        function closeDialog(result) {
            // Remove event listeners
            document.removeEventListener('keydown', handleKeyDown);
            overlay.removeEventListener('click', handleOverlayClick);
            
            // Remove modal from DOM
            document.body.removeChild(overlay);
            
            // Restore previous focus
            if (previousActiveElement && previousActiveElement.focus) {
                previousActiveElement.focus();
            }
            
            resolve(result);
        }
        
        // Handle keyboard events
        function handleKeyDown(e) {
            // Escape key closes dialog (returns false)
            if (e.key === 'Escape') {
                e.preventDefault();
                closeDialog(false);
                return;
            }
            
            // Tab key: trap focus within dialog
            if (e.key === 'Tab') {
                e.preventDefault();
                const currentIndex = focusableElements.indexOf(document.activeElement);
                let nextIndex;
                
                if (e.shiftKey) {
                    // Shift+Tab: move backwards
                    nextIndex = currentIndex <= 0 ? focusableElements.length - 1 : currentIndex - 1;
                } else {
                    // Tab: move forwards
                    nextIndex = currentIndex >= focusableElements.length - 1 ? 0 : currentIndex + 1;
                }
                
                focusableElements[nextIndex].focus();
            }
        }
        
        // Handle overlay click (dismiss dialog)
        function handleOverlayClick(e) {
            if (e.target === overlay) {
                closeDialog(false);
            }
        }
        
        // Button click handlers
        cancelBtn.addEventListener('click', () => closeDialog(false));
        confirmBtn.addEventListener('click', () => closeDialog(true));
        
        // Attach event listeners
        document.addEventListener('keydown', handleKeyDown);
        overlay.addEventListener('click', handleOverlayClick);
    });
};

// Utility function for HTML escaping (reuse global if available)
if (typeof window.escapeHtml !== 'function') {
    window.escapeHtml = function(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    };
}

/**
 * ResizableSplit - Makes a two-pane layout resizable with a draggable divider.
 * 
 * Usage:
 *   const split = new ResizableSplit(containerElement, {
 *     defaultSplit: 60,  // percentage for left pane
 *     minSplit: 20,
 *     maxSplit: 80,
 *     storageKey: 'my-split-position'
 *   });
 * 
 * Lifecycle:
 *   split.destroy() - removes event listeners and cleanup
 */

class ResizableSplit {
    constructor(container, options = {}) {
        this.container = container;
        this.options = {
            defaultSplit: options.defaultSplit || 60,
            minSplit: options.minSplit || 20,
            maxSplit: options.maxSplit || 80,
            storageKey: options.storageKey || 'dag-dashboard.run-detail.split',
            mobileBreakpoint: options.mobileBreakpoint || 1024
        };
        
        this.isDragging = false;
        this.currentSplit = this._loadSplit();
        
        // Store original content
        this.leftContent = container.querySelector('.run-graph-canvas');
        this.rightContent = container.querySelector('.run-graph-side');
        
        if (!this.leftContent || !this.rightContent) {
            console.warn('ResizableSplit: could not find .run-graph-canvas and .run-graph-side');
            return;
        }
        
        // Build split structure
        this._buildStructure();
        
        // Check if we're on mobile
        this.mediaQuery = window.matchMedia(`(max-width: ${this.options.mobileBreakpoint}px)`);
        this._updateLayout();
        
        // Bind event handlers
        this._onPointerDown = this._handlePointerDown.bind(this);
        this._onPointerMove = this._handlePointerMove.bind(this);
        this._onPointerUp = this._handlePointerUp.bind(this);
        this._onMediaChange = this._updateLayout.bind(this);
        
        // Attach listeners
        this.divider.addEventListener('pointerdown', this._onPointerDown);
        this.mediaQuery.addEventListener('change', this._onMediaChange);
        
        // Use ResizeObserver as fallback for window resize
        this.resizeObserver = new ResizeObserver(() => {
            this._updateLayout();
        });
        this.resizeObserver.observe(this.container);
    }
    
    _buildStructure() {
        // Wrap the container with split classes
        this.container.classList.add('run-split');
        
        // Create wrapper divs
        this.leftPane = document.createElement('div');
        this.leftPane.className = 'run-split-left';
        this.leftPane.appendChild(this.leftContent);
        
        this.divider = document.createElement('div');
        this.divider.className = 'run-split-divider';
        this.divider.setAttribute('aria-label', 'Resize divider');
        this.divider.setAttribute('role', 'separator');
        
        this.rightPane = document.createElement('div');
        this.rightPane.className = 'run-split-right';
        this.rightPane.appendChild(this.rightContent);
        
        // Clear and rebuild container
        this.container.innerHTML = '';
        this.container.appendChild(this.leftPane);
        this.container.appendChild(this.divider);
        this.container.appendChild(this.rightPane);
        
        // Apply initial split
        this._applySplit(this.currentSplit);
    }
    
    _loadSplit() {
        try {
            const stored = localStorage.getItem(this.options.storageKey);
            if (stored) {
                const parsed = parseFloat(stored);
                if (!isNaN(parsed)) {
                    return Math.max(
                        this.options.minSplit,
                        Math.min(this.options.maxSplit, parsed)
                    );
                }
            }
        } catch (e) {
            console.warn('ResizableSplit: could not load from localStorage', e);
        }
        return this.options.defaultSplit;
    }
    
    _saveSplit(value) {
        try {
            localStorage.setItem(this.options.storageKey, value.toString());
        } catch (e) {
            console.warn('ResizableSplit: could not save to localStorage', e);
        }
    }
    
    _applySplit(percentage) {
        if (!this.leftPane) return;
        this.leftPane.style.flexBasis = `${percentage}%`;
        this.currentSplit = percentage;
    }
    
    _updateLayout() {
        const isMobile = this.mediaQuery.matches;
        
        if (isMobile) {
            this.container.setAttribute('data-stacked', 'true');
            this.divider.style.display = 'none';
        } else {
            this.container.removeAttribute('data-stacked');
            this.divider.style.display = '';
            this._applySplit(this.currentSplit);
        }
    }
    
    _handlePointerDown(e) {
        if (this.mediaQuery.matches) return; // No dragging on mobile
        
        e.preventDefault();
        this.isDragging = true;
        
        // Capture pointer to receive events even if cursor leaves divider
        this.divider.setPointerCapture(e.pointerId);
        
        document.addEventListener('pointermove', this._onPointerMove);
        document.addEventListener('pointerup', this._onPointerUp);
        
        this.container.classList.add('resizing');
    }
    
    _handlePointerMove(e) {
        if (!this.isDragging) return;
        
        const containerRect = this.container.getBoundingClientRect();
        const offsetX = e.clientX - containerRect.left;
        const percentage = (offsetX / containerRect.width) * 100;
        
        const clamped = Math.max(
            this.options.minSplit,
            Math.min(this.options.maxSplit, percentage)
        );
        
        this._applySplit(clamped);
    }
    
    _handlePointerUp(e) {
        if (!this.isDragging) return;
        
        this.isDragging = false;
        this.divider.releasePointerCapture(e.pointerId);
        
        document.removeEventListener('pointermove', this._onPointerMove);
        document.removeEventListener('pointerup', this._onPointerUp);
        
        this.container.classList.remove('resizing');
        
        // Save final position
        this._saveSplit(this.currentSplit);
    }
    
    destroy() {
        // Remove event listeners
        if (this.divider) {
            this.divider.removeEventListener('pointerdown', this._onPointerDown);
        }
        
        if (this.mediaQuery) {
            this.mediaQuery.removeEventListener('change', this._onMediaChange);
        }
        
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
        }
        
        document.removeEventListener('pointermove', this._onPointerMove);
        document.removeEventListener('pointerup', this._onPointerUp);
        
        // Clean up classes
        if (this.container) {
            this.container.classList.remove('run-split', 'resizing');
            this.container.removeAttribute('data-stacked');
        }
        
        // Note: we don't restore the original DOM structure on destroy
        // as that would be disruptive during navigation
    }
}

// Export to window for use in app.js
window.ResizableSplit = ResizableSplit;

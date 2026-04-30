/**
 * StateSlideover — slide-over panel for state channels, timeline, and artifacts.
 *
 * Architecture (eager mount, Option A):
 * - DOM is created on page load with .state-slideover--closed class (CSS display:none)
 * - The three containers (channel-state-container, state-diff-timeline-container,
 *   run-artifacts-container) exist in the DOM from page load
 * - Opening/closing is a CSS class toggle
 * - This preserves existing poll semantics for live updates without user interaction
 *
 * Usage:
 *   StateSlideover.mount('container-id');
 *   StateSlideover.open();
 *   StateSlideover.close();
 */

(function (window) {
    'use strict';

    let slideoverElement = null;

    const StateSlideover = {
        /**
         * Mount the slideover DOM structure (eager mount).
         * Called from renderRunDetail in app.js.
         */
        mount(containerId) {
            const container = document.getElementById(containerId);
            if (!container) {
                console.warn(`StateSlideover: container #${containerId} not found`);
                return;
            }

            // Create slideover structure with closed state
            const html = `
                <div class="state-slideover state-slideover--closed">
                    <div class="state-slideover-backdrop"></div>
                    <div class="state-slideover-panel">
                        <div class="state-slideover-header">
                            <h3>Workflow State</h3>
                            <button class="state-slideover-close" aria-label="Close">&times;</button>
                        </div>
                        <div class="state-slideover-body">
                            <h4 class="state-slideover-section-title">State Channels</h4>
                            <div id="channel-state-container"></div>
                            
                            <h4 class="state-slideover-section-title">State Changes Timeline</h4>
                            <div id="state-diff-timeline-container"></div>
                            
                            <h4 class="state-slideover-section-title">Artifacts</h4>
                            <div id="run-artifacts-container"></div>
                        </div>
                    </div>
                </div>
            `;

            container.innerHTML = html;
            slideoverElement = container.querySelector('.state-slideover');

            // Attach close handlers
            const closeBtn = slideoverElement.querySelector('.state-slideover-close');
            const backdrop = slideoverElement.querySelector('.state-slideover-backdrop');

            if (closeBtn) {
                closeBtn.addEventListener('click', () => StateSlideover.close());
            }
            if (backdrop) {
                backdrop.addEventListener('click', () => StateSlideover.close());
            }

            // Containers are now in the DOM and ready for live updates
        },

        /**
         * Open the slideover (CSS class toggle).
         */
        open() {
            if (slideoverElement) {
                slideoverElement.classList.remove('state-slideover--closed');
            }
        },

        /**
         * Close the slideover (CSS class toggle).
         */
        close() {
            if (slideoverElement) {
                slideoverElement.classList.add('state-slideover--closed');
            }
        },

        /**
         * Toggle the slideover open/closed state.
         */
        toggle() {
            if (slideoverElement) {
                if (slideoverElement.classList.contains('state-slideover--closed')) {
                    StateSlideover.open();
                } else {
                    StateSlideover.close();
                }
            }
        },

        /**
         * Check if the slideover is currently open.
         */
        isOpen() {
            return slideoverElement && !slideoverElement.classList.contains('state-slideover--closed');
        },

        /**
         * Cleanup (on route change).
         */
        destroy() {
            if (slideoverElement && slideoverElement.parentNode) {
                slideoverElement.parentNode.removeChild(slideoverElement);
            }
            slideoverElement = null;
        }
    };

    // Export to global scope
    window.StateSlideover = StateSlideover;

})(window);

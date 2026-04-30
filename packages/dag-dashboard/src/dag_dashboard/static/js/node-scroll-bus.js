/**
 * NodeScrollBus — singleton event bus for DAG-feed cross-selection.
 *
 * Coordinates scroll/highlight between:
 * - DAG nodes (dag-renderer.js)
 * - Progress card feed items (workflow-progress-card.js)
 *
 * Usage:
 *   const bus = NodeScrollBus.getInstance();
 *   bus.subscribe((nodeId) => { /* scroll to nodeId */ });
 *   bus.notifyNodeClicked('step1');
 */

(function (window) {
    'use strict';

    let instance = null;

    class NodeScrollBus {
        constructor() {
            if (instance) {
                return instance;
            }

            this.subscribers = [];
            instance = this;
        }

        /**
         * Subscribe to node click events.
         * @param {Function} callback - Called with (nodeId, source) when a node is clicked
         *                              source is 'dag' or 'card'
         */
        subscribe(callback) {
            if (typeof callback === 'function') {
                this.subscribers.push(callback);
            }
        }

        /**
         * Unsubscribe a callback
         */
        unsubscribe(callback) {
            const index = this.subscribers.indexOf(callback);
            if (index > -1) {
                this.subscribers.splice(index, 1);
            }
        }

        /**
         * Notify all subscribers that a DAG node was clicked.
         */
        notifyNodeClicked(nodeId) {
            this.subscribers.forEach((callback) => {
                try {
                    callback(nodeId, 'dag');
                } catch (e) {
                    console.error('NodeScrollBus: subscriber error', e);
                }
            });
        }

        /**
         * Notify all subscribers that a progress card was clicked.
         */
        notifyCardClicked(nodeId) {
            this.subscribers.forEach((callback) => {
                try {
                    callback(nodeId, 'card');
                } catch (e) {
                    console.error('NodeScrollBus: subscriber error', e);
                }
            });
        }

        /**
         * Clear all subscribers (useful for cleanup on route change).
         */
        clear() {
            this.subscribers = [];
        }

        /**
         * Get the singleton instance.
         */
        static getInstance() {
            if (!instance) {
                instance = new NodeScrollBus();
            }
            return instance;
        }
    }

    // Export to global scope
    window.NodeScrollBus = NodeScrollBus;

})(window);

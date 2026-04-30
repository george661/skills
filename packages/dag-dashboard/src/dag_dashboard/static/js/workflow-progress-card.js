/**
 * WorkflowProgressCard — unified DAG-linked conversation feed.
 *
 * Renders a vertically-scrollable list of message cards derived from SSE events
 * (node_started, channel_write, node_completed, escalation_resumed, etc.).
 *
 * Architecture:
 * - eventToMessages.js buffers orphan channel writes until node_started arrives
 *   (handles out-of-order SSE)
 * - node-scroll-bus.js coordinates cross-selection between DAG nodes and feed cards
 * - Each card has a data-node-id attribute for jump/highlight
 *
 * Usage:
 *   const card = new WorkflowProgressCard('container-id', runId);
 *   card.handleSSEMessage({ type: 'node_started', node_id: 'step1', ... });
 */

(function (window) {
    'use strict';

    class WorkflowProgressCard {
        constructor(containerId, runId) {
            this.containerId = containerId;
            this.runId = runId;
            this.container = document.getElementById(containerId);
            
            if (!this.container) {
                console.warn(`WorkflowProgressCard: container #${containerId} not found`);
                return;
            }

            this.messages = [];
            this.nodeScrollBus = window.NodeScrollBus ? window.NodeScrollBus.getInstance() : null;
        }

        /**
         * Process SSE event and update the feed.
         * Delegates event-to-message conversion to eventToMessages helper.
         * Called from setupLiveUpdates with normalized event shape.
         */
        handleEvent(event) {
            if (!event || !event.event_type) return;

            // Normalize to the shape expected by eventToMessages
            const normalized = {
                type: event.event_type,
                node_id: event.node_id,
                node_name: event.metadata?.node_name || event.node_name,
                timestamp: event.timestamp,
                ...event.metadata
            };

            // Convert SSE event to message objects
            if (window.eventToMessages) {
                const newMessages = window.eventToMessages(normalized);
                if (newMessages && newMessages.length > 0) {
                    this.messages.push(...newMessages);
                    this.render();
                }
            }
        }

        /**
         * Alias for backward compatibility
         */
        handleSSEMessage(event) {
            return this.handleEvent(event);
        }

        /**
         * Render the entire feed from scratch.
         * Each message card includes data-node-id for scroll targeting.
         */
        render() {
            if (!this.container) return;

            const html = this.messages
                .map((msg) => this.renderMessage(msg))
                .join('');

            this.container.innerHTML = html || '<div class="progress-card-empty">No messages yet</div>';

            // Register click handlers for cross-selection
            if (this.nodeScrollBus) {
                this.container.querySelectorAll('.progress-card-item').forEach((el) => {
                    const nodeId = el.getAttribute('data-node-id');
                    if (nodeId) {
                        el.addEventListener('click', () => {
                            this.nodeScrollBus.notifyCardClicked(nodeId);
                        });
                    }
                });
            }
        }

        /**
         * Render a single message card based on type.
         */
        renderMessage(msg) {
            const nodeId = msg.nodeId || '';
            const classes = ['progress-card-item', `progress-card-item--${msg.type}`];
            
            if (msg.highlight) classes.push('progress-card-item--highlight');

            let content = '';
            switch (msg.type) {
                case 'node_started':
                    content = `<strong>${this.escapeHtml(msg.nodeName || nodeId)}</strong> started`;
                    break;
                case 'node_completed':
                    content = `<strong>${this.escapeHtml(msg.nodeName || nodeId)}</strong> completed`;
                    break;
                case 'channel_write':
                    content = `<strong>${this.escapeHtml(msg.nodeName || nodeId)}</strong> wrote to channel <code>${this.escapeHtml(msg.channel)}</code>`;
                    if (msg.preview) {
                        content += `<pre class="progress-card-preview">${this.escapeHtml(msg.preview)}</pre>`;
                    }
                    break;
                case 'escalation':
                    content = `<strong>Escalation</strong>: ${this.escapeHtml(msg.message || 'Node escalated')}`;
                    break;
                case 'escalation_resumed':
                    content = `<strong>Escalation resumed</strong> for ${this.escapeHtml(msg.nodeName || nodeId)}`;
                    break;
                default:
                    content = this.escapeHtml(JSON.stringify(msg));
            }

            return `
                <div class="${classes.join(' ')}" data-node-id="${this.escapeHtml(nodeId)}">
                    <div class="progress-card-timestamp">${this.formatTimestamp(msg.timestamp)}</div>
                    <div class="progress-card-content">${content}</div>
                </div>
            `;
        }

        /**
         * Scroll to a specific node's card in the feed.
         * Called via NodeScrollBus when DAG node is clicked.
         */
        scrollToNode(nodeId) {
            if (!this.container) return;

            const card = this.container.querySelector(`[data-node-id="${CSS.escape(nodeId)}"]`);
            if (card) {
                card.scrollIntoView({ behavior: 'smooth', block: 'center' });
                card.classList.add('progress-card-item--highlight');
                setTimeout(() => card.classList.remove('progress-card-item--highlight'), 2000);
            }
        }

        /**
         * Cleanup
         */
        destroy() {
            if (this.container) {
                this.container.innerHTML = '';
            }
            this.messages = [];
        }

        // Helpers
        escapeHtml(str) {
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }

        formatTimestamp(ts) {
            if (!ts) return '';
            const date = new Date(ts);
            return date.toLocaleTimeString();
        }
    }

    // Export to global scope
    window.WorkflowProgressCard = WorkflowProgressCard;

})(window);

/**
 * eventToMessages — SSE event-to-message conversion with channel write folding.
 *
 * Architecture:
 * - SSE events can arrive out-of-order (channel_write before node_started)
 * - We buffer orphan channel writes in state.pendingChannels[writer_node_id]
 * - When node_started arrives, we flush the buffer and create message cards
 *
 * Usage:
 *   const messages = eventToMessages({ type: 'node_started', node_id: 'step1', ... });
 *   messages.forEach(msg => progressCard.addMessage(msg));
 */

(function (window) {
    'use strict';

    // Global state for buffering orphan channel writes
    const state = {
        pendingChannels: {}, // { writer_node_id: [channelWriteEvent, ...] }
        nodeNames: {}        // { node_id: node_name } cache
    };

    /**
     * Convert a single SSE event to an array of message objects.
     * Returns [] if event should be ignored.
     */
    function eventToMessages(event) {
        if (!event || !event.type) return [];

        const messages = [];

        switch (event.type) {
            case 'node_started':
                messages.push({
                    type: 'node_started',
                    nodeId: event.node_id,
                    nodeName: event.node_name,
                    timestamp: event.timestamp || new Date().toISOString()
                });

                // Cache node name
                if (event.node_id && event.node_name) {
                    state.nodeNames[event.node_id] = event.node_name;
                }

                // Flush any pending channel writes for this node
                const pending = state.pendingChannels[event.node_id];
                if (pending && pending.length > 0) {
                    pending.forEach((channelEvent) => {
                        messages.push(convertChannelWrite(channelEvent));
                    });
                    delete state.pendingChannels[event.node_id];
                }
                break;

            case 'node_completed':
                messages.push({
                    type: 'node_completed',
                    nodeId: event.node_id,
                    nodeName: event.node_name || state.nodeNames[event.node_id],
                    timestamp: event.timestamp || new Date().toISOString(),
                    status: event.status
                });
                break;

            case 'channel_write':
                const writerNodeId = event.writer_node_id || event.node_id;
                
                // If we have the node name already, create message immediately
                if (state.nodeNames[writerNodeId]) {
                    messages.push(convertChannelWrite(event));
                } else {
                    // Buffer until node_started arrives
                    if (!state.pendingChannels[writerNodeId]) {
                        state.pendingChannels[writerNodeId] = [];
                    }
                    state.pendingChannels[writerNodeId].push(event);
                }
                break;

            case 'escalation':
                messages.push({
                    type: 'escalation',
                    nodeId: event.node_id,
                    nodeName: event.node_name || state.nodeNames[event.node_id],
                    message: event.error || event.message,
                    timestamp: event.timestamp || new Date().toISOString()
                });
                break;

            case 'escalation_resumed':
                messages.push({
                    type: 'escalation_resumed',
                    nodeId: event.node_id,
                    nodeName: event.node_name || state.nodeNames[event.node_id],
                    timestamp: event.timestamp || new Date().toISOString()
                });
                break;

            // Add other event types as needed
            default:
                // Unknown event type — ignore
                break;
        }

        return messages;
    }

    /**
     * Convert a channel_write event to a message object.
     */
    function convertChannelWrite(event) {
        const writerNodeId = event.writer_node_id || event.node_id;
        const nodeName = event.writer_node_name || state.nodeNames[writerNodeId] || writerNodeId;

        let preview = '';
        if (event.value) {
            try {
                const val = typeof event.value === 'string' ? event.value : JSON.stringify(event.value);
                preview = val.substring(0, 200);
                if (val.length > 200) preview += '...';
            } catch (e) {
                preview = String(event.value).substring(0, 200);
            }
        }

        return {
            type: 'channel_write',
            nodeId: writerNodeId,
            nodeName: nodeName,
            channel: event.channel,
            preview: preview,
            timestamp: event.timestamp || new Date().toISOString()
        };
    }

    /**
     * Reset state (useful for testing or when navigating away from run detail).
     */
    function resetState() {
        state.pendingChannels = {};
        state.nodeNames = {};
    }

    // Export to global scope
    window.eventToMessages = eventToMessages;
    window.eventToMessages.resetState = resetState;

})(window);

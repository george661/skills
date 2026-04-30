/**
 * event-to-messages — SSE event → feed-message conversion.
 *
 * The unified conversation feed is a list of typed messages. Every SSE event
 * from the workflow SSE stream is translated into one of these message shapes:
 *
 *   { type: 'progress_card', nodeId, subtype, payload }
 *   { type: 'terminal', status, payload }
 *
 * `progress_card` messages are routed to per-node WorkflowProgressCard
 * instances (one card per node). `subtype` is the original event_type
 * (`node_started`, `node_log_line`, `node_stream_token`, `channel_updated`,
 * `node_completed`, `node_failed`, `node_skipped`, `node_interrupted`,
 * `node_escalated`). The card decides how to render each subtype.
 *
 * Channel writes (`channel_updated`) are not top-level feed messages — they
 * fold into the owning card via `metadata.writer_node_id`. If a channel write
 * arrives before the owning node_started (SSE reconnect backfill), it's
 * buffered in state.pendingChannels[writerNodeId] and flushed when the
 * corresponding node_started arrives.
 *
 * `terminal` messages mark workflow-level end states and render as a footer
 * banner in the feed.
 */

(function (window) {
    'use strict';

    /**
     * Create a fresh state object. Callers keep one per feed instance so
     * orphan channel writes buffered at connect time are flushed on the
     * matching node_started.
     */
    function createState() {
        return {
            seenNodes: new Set(),
            pendingChannels: {}, // { writer_node_id: [event, ...] }
        };
    }

    /**
     * Convert one SSE event to zero-or-more feed messages.
     *
     * @param {object} event Normalized event: { event_type, node_id, metadata, timestamp, model, dispatch, duration_ms }
     * @param {object} state Mutable state from createState()
     * @returns {Array<object>} messages
     */
    function eventToMessages(event, state) {
        if (!event || !event.event_type) return [];
        if (!state) state = createState();

        const t = event.event_type;
        const meta = event.metadata || {};

        switch (t) {
            case 'workflow_started':
                // Not a feed entry — handled by banner elsewhere.
                return [];

            case 'node_started': {
                const nodeId = event.node_id;
                if (!nodeId) return [];
                const messages = [{
                    type: 'progress_card',
                    nodeId,
                    subtype: 'node_started',
                    payload: event,
                }];
                state.seenNodes.add(nodeId);
                const pending = state.pendingChannels[nodeId];
                if (pending && pending.length) {
                    pending.forEach((chEvent) => {
                        messages.push({
                            type: 'progress_card',
                            nodeId,
                            subtype: 'channel_updated',
                            payload: chEvent,
                        });
                    });
                    delete state.pendingChannels[nodeId];
                }
                return messages;
            }

            case 'node_log_line':
            case 'node_stream_token':
            case 'node_progress': {
                const nodeId = event.node_id;
                if (!nodeId) return [];
                // Suppress retry-style node_progress events (those carry an
                // `attempt` counter and are handled by the DAG retry overlay,
                // not the feed).
                if (t === 'node_progress' && meta.attempt != null) return [];
                return [{
                    type: 'progress_card',
                    nodeId,
                    subtype: t,
                    payload: event,
                }];
            }

            case 'channel_updated': {
                const writerNodeId = meta.writer_node_id || event.node_id;
                if (!writerNodeId) return [];
                // Fold into owning card if it's already been seen; otherwise
                // buffer until node_started arrives.
                if (state.seenNodes.has(writerNodeId)) {
                    return [{
                        type: 'progress_card',
                        nodeId: writerNodeId,
                        subtype: 'channel_updated',
                        payload: event,
                    }];
                }
                if (!state.pendingChannels[writerNodeId]) {
                    state.pendingChannels[writerNodeId] = [];
                }
                state.pendingChannels[writerNodeId].push(event);
                return [];
            }

            case 'node_completed':
            case 'node_failed':
            case 'node_skipped':
            case 'node_interrupted':
            case 'node_escalated': {
                const nodeId = event.node_id;
                if (!nodeId) return [];
                return [{
                    type: 'progress_card',
                    nodeId,
                    subtype: t,
                    payload: event,
                }];
            }

            case 'workflow_completed':
            case 'workflow_failed':
            case 'workflow_interrupted':
            case 'workflow_cancelled':
                return [{
                    type: 'terminal',
                    status: t.replace('workflow_', ''),
                    payload: event,
                }];

            default:
                return [];
        }
    }

    window.EventToMessages = {
        createState,
        eventToMessages,
    };
})(window);

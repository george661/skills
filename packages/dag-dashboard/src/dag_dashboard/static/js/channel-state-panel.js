/**
 * Channel State Panel - displays workflow channel states with live updates
 */

// Security: HTML escaping helper to prevent XSS
function escapeHtml(unsafe) {
    if (unsafe === null || unsafe === undefined) return '';
    return String(unsafe)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

class ChannelStatePanel {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.channels = [];
    }

    /**
     * Update panel with new channel data
     * @param {Array} channels - Array of channel state objects
     */
    update(channels) {
        this.channels = channels;
        this.render();
    }

    /**
     * Render the channel state panel as a vertical stack of cards — works in
     * narrow right-rail columns where a 5-column table previously hid the
     * rightmost columns and truncated values.
     */
    render() {
        if (!this.container) return;

        if (this.channels.length === 0) {
            this.container.innerHTML = '<p class="empty-state">No channels written yet.</p>';
            return;
        }

        const html = `
            <div class="channel-state-panel">
                ${this.channels.map(ch => this.renderChannelCard(ch)).join('')}
            </div>
        `;
        this.container.innerHTML = html;
    }

    /**
     * Render a single channel as a stacked card.
     * @param {Object} channel - Channel state object
     */
    renderChannelCard(channel) {
        const hasConflict = channel.conflict !== null;
        const conflictClass = hasConflict ? 'channel-conflict' : '';
        // Smart value formatting — identical logic to state-diff-timeline:
        // raw strings shown unquoted; ```json ... ``` fenced blocks
        // unwrapped + pretty-printed; objects/arrays pretty-printed.
        // Without this, JSON.stringify on a raw string wraps it in quotes
        // and converts newlines to literal \n, so the pre block becomes a
        // single wide line that runs off the panel.
        const formatChannelValue = (v) => {
            if (v === null || v === undefined) return '';
            if (typeof v === 'string') {
                const fenced = v.trim().match(/^```(?:json)?\s*\n?([\s\S]*?)\n?```$/);
                const candidate = fenced ? fenced[1] : v.trim();
                if (candidate.startsWith('{') || candidate.startsWith('[')) {
                    try { return JSON.stringify(JSON.parse(candidate), null, 2); } catch { /* fall through */ }
                }
                return v;
            }
            try { return JSON.stringify(v, null, 2); } catch { return String(v); }
        };
        const value = escapeHtml(formatChannelValue(channel.value));
        const reducerBadge = channel.reducer_strategy
            ? `<span class="reducer-badge">${escapeHtml(channel.reducer_strategy)}</span>`
            : '';

        const writersList = channel.writers.map(escapeHtml).join(', ');
        const conflictMsg = hasConflict
            ? `<div class="conflict-message">${escapeHtml(channel.conflict.message)}</div>`
            : '';

        return `
            <div class="channel-card ${conflictClass}">
                <div class="channel-card-head">
                    <span class="channel-card-key">${escapeHtml(channel.channel_key)}</span>
                    <span class="channel-card-meta">
                        <span class="channel-card-type">${escapeHtml(channel.channel_type)}</span>
                        ${reducerBadge}
                        <span class="channel-card-version" title="Version">v${escapeHtml(String(channel.version))}</span>
                    </span>
                </div>
                <pre class="channel-value">${value}</pre>
                ${writersList ? `<div class="channel-card-writers">Writers: ${writersList}</div>` : ''}
                ${conflictMsg}
            </div>
        `;
    }
}

// Export for use in app.js
window.ChannelStatePanel = ChannelStatePanel;

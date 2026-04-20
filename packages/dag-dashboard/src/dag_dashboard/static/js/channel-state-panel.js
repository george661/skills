/**
 * Channel State Panel - displays workflow channel states with live updates
 */

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
     * Render the channel state table
     */
    render() {
        if (!this.container) return;

        if (this.channels.length === 0) {
            this.container.innerHTML = '<p class="empty-state">No channels defined for this workflow.</p>';
            return;
        }

        const html = `
            <div class="channel-state-panel">
                <h3>Channel State</h3>
                <table class="channel-table">
                    <thead>
                        <tr>
                            <th>Channel</th>
                            <th>Type</th>
                            <th>Value</th>
                            <th>Version</th>
                            <th>Writers</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${this.channels.map(ch => this.renderChannelRow(ch)).join('')}
                    </tbody>
                </table>
            </div>
        `;
        this.container.innerHTML = html;
    }

    /**
     * Render a single channel row
     * @param {Object} channel - Channel state object
     */
    renderChannelRow(channel) {
        const hasConflict = channel.conflict !== null;
        const conflictClass = hasConflict ? 'channel-conflict' : '';
        const value = JSON.stringify(channel.value, null, 2);
        const reducerBadge = channel.reducer_strategy 
            ? `<span class="reducer-badge">${channel.reducer_strategy}</span>` 
            : '';
        
        const writersList = channel.writers.join(', ');
        const conflictMsg = hasConflict 
            ? `<div class="conflict-message">${channel.conflict.message}</div>` 
            : '';

        return `
            <tr class="${conflictClass}">
                <td><strong>${channel.channel_key}</strong></td>
                <td>${channel.channel_type} ${reducerBadge}</td>
                <td><pre class="channel-value">${value}</pre></td>
                <td>${channel.version}</td>
                <td>${writersList}${conflictMsg}</td>
            </tr>
        `;
    }
}

// Export for use in app.js
window.ChannelStatePanel = ChannelStatePanel;

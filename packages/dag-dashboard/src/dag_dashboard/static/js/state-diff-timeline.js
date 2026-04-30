/**
 * State Diff Timeline - Visualize channel state changes per node execution
 */

/**
 * Render state diff timeline for a workflow run
 * @param {HTMLElement} container - Container to render timeline into
 * @param {string} runId - Workflow run ID
 */
async function renderStateDiffTimeline(container, runId) {
    if (!container || !runId) {
        console.warn('renderStateDiffTimeline: missing container or runId');
        return;
    }

    try {
        const response = await fetch(`/api/workflows/${runId}/state-diff-timeline`);

        if (!response.ok) {
            if (response.status === 404) {
                container.innerHTML = '<p class="timeline-empty">Workflow run not found</p>';
                return;
            }
            throw new Error(`HTTP ${response.status}`);
        }

        const timeline = await response.json();

        // Defensive: the endpoint returns a JSON array, but older servers or
        // partial responses may hand back an object or null. Bail cleanly in
        // those cases instead of throwing ".map is not a function".
        if (!Array.isArray(timeline) || timeline.length === 0) {
            container.innerHTML = '<p class="timeline-empty">No state changes yet</p>';
            return;
        }

        // Preserve expand state across polling-driven re-renders: the
        // run-detail page polls /state-diff-timeline every 2s. Without this,
        // every poll wipes the DOM and the user's clicked-expanded rows snap
        // shut. We key by "{nodeName}::{changeKey}" — node+channel is stable
        // across polls.
        const expandedKeys = new Set(
            Array.from(container.querySelectorAll('.diff-row .diff-values.expanded'))
                .map(el => el.closest('.diff-row')?.dataset.expandKey)
                .filter(Boolean)
        );

        // Render timeline
        const timelineHtml = timeline.map(nodeEntry => renderNodeEntry(nodeEntry)).join('');
        container.innerHTML = `<div class="state-diff-timeline">${timelineHtml}</div>`;

        // Restore prior expanded rows
        container.querySelectorAll('.diff-row').forEach(row => {
            if (expandedKeys.has(row.dataset.expandKey)) {
                row.querySelector('.diff-values')?.classList.add('expanded');
            }
        });

        // Wire expand/collapse handlers
        container.querySelectorAll('.diff-row').forEach(row => {
            row.addEventListener('click', () => {
                const valuesDiv = row.querySelector('.diff-values');
                if (valuesDiv) {
                    valuesDiv.classList.toggle('expanded');
                }
            });
        });

    } catch (error) {
        console.error('Error fetching state diff timeline:', error);
        container.innerHTML = `<p class="timeline-error">Error loading timeline: ${escapeHtml(error.message)}</p>`;
    }
}

/**
 * Render a single node entry in the timeline
 * @param {Object} nodeEntry - Node state diff entry
 * @returns {string} HTML string
 */
function renderNodeEntry(nodeEntry) {
    const { node_name, node_id, started_at, finished_at, changes } = nodeEntry;

    // Format timestamps
    const startTime = started_at ? new Date(started_at).toLocaleTimeString() : 'N/A';
    const endTime = finished_at ? new Date(finished_at).toLocaleTimeString() : 'N/A';

    // Render changes (pass node_name so each row can carry a stable expand key)
    const changesHtml = changes.map(change => renderChange(change, node_name)).join('');

    return `
        <div class="diff-node">
            <div class="diff-node-header">
                <strong>${escapeHtml(node_name)}</strong>
                <span class="diff-node-time">${startTime} - ${endTime}</span>
            </div>
            <div class="diff-changes">
                ${changesHtml || '<p class="no-changes">No changes</p>'}
            </div>
        </div>
    `;
}

/**
 * Render a single change entry
 * @param {Object} change - Change object with key, change_type, before, after
 * @returns {string} HTML string
 */
function renderChange(change, nodeName) {
    const { key, change_type, before, after } = change;

    // Choose CSS class based on change type
    const cssClass = `diff-${change_type}`;

    // Icon for change type
    const icon = {
        added: '➕',
        changed: '✏️',
        removed: '➖'
    }[change_type] || '•';

    const beforeDisplay = formatValueForDisplay(before);
    const afterDisplay = formatValueForDisplay(after);

    // Stable expand key so polling-driven re-renders can restore state.
    const expandKey = `${nodeName || '?'}::${key}`;

    // For ADDED rows the "Before" is always null — hide it to reduce noise.
    // For REMOVED rows the "After" is always null — hide it too.
    const showBefore = change_type !== 'added';
    const showAfter = change_type !== 'removed';

    return `
        <div class="diff-row ${cssClass}" data-expand-key="${escapeHtml(expandKey)}">
            <div class="diff-row-header">
                <span class="diff-icon">${icon}</span>
                <span class="diff-key">${escapeHtml(key)}</span>
                <span class="diff-type">${escapeHtml(change_type)}</span>
                <span class="diff-chevron">▼</span>
            </div>
            <div class="diff-values">
                ${showBefore ? `
                <div class="diff-value-pair">
                    <div class="diff-value-label">Before:</div>
                    <pre class="diff-value-content">${escapeHtml(beforeDisplay)}</pre>
                </div>` : ''}
                ${showAfter ? `
                <div class="diff-value-pair">
                    <div class="diff-value-label">After:</div>
                    <pre class="diff-value-content">${escapeHtml(afterDisplay)}</pre>
                </div>` : ''}
            </div>
        </div>
    `;
}

/**
 * Format a channel value for display in the diff panel.
 *
 * Priority:
 *   - null/undefined → explicit placeholder.
 *   - String that parses as JSON (possibly wrapped in ```json fences, which
 *     is what prompt-runner output looks like) → pretty-printed JSON.
 *   - Any other string → shown raw (no surrounding quotes, no \n escapes).
 *   - Objects/arrays → pretty-printed JSON.
 *   - Fallback → String(v).
 */
function formatValueForDisplay(v) {
    if (v === null) return 'null';
    if (v === undefined) return '(unset)';
    if (typeof v === 'string') {
        // Strip common ```json ... ``` fences before parsing.
        const fenced = v.trim().match(/^```(?:json)?\s*\n?([\s\S]*?)\n?```$/);
        const candidate = fenced ? fenced[1] : v.trim();
        if (candidate.startsWith('{') || candidate.startsWith('[')) {
            try {
                return JSON.stringify(JSON.parse(candidate), null, 2);
            } catch { /* fall through to raw */ }
        }
        return v;
    }
    try { return JSON.stringify(v, null, 2); } catch { return String(v); }
}

// Export for use in app.js
if (typeof window !== 'undefined') {
    window.renderStateDiffTimeline = renderStateDiffTimeline;
}

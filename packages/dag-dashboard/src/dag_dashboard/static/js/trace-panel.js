/**
 * TracePanel — live execution trace for a workflow run.
 *
 * This is the chat-style feed the user wants to watch while a workflow runs.
 * Inspired by Archon's WorkflowLogs: each node gets a collapsible card that
 * shows its live elapsed time, streaming content (stdout, LLM tokens), any
 * channel writes it produced, and the final status / error.
 *
 * Design notes:
 *   - Consumes the same SSE event stream the DAG renderer listens to.
 *   - Renders a single scrolling feed of per-node cards in arrival order.
 *   - Keeps a sticky "Currently executing" banner at the top of the feed so
 *     the node-in-flight stays visible even when the user scrolls back.
 *   - Auto-scrolls to the newest content unless the user scrolled up (so
 *     they can inspect earlier nodes without the feed yanking them).
 *   - Exposes scrollToNode(nodeId) so a DAG-node click can jump the feed.
 */

class TracePanel {
    constructor(containerId, runId) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        if (!this.container) {
            throw new Error(`TracePanel container #${containerId} not found`);
        }
        this.runId = runId;

        // node_id → { el, bodyEl, startedAt, timerHandle, logLines, tokenBuf, status }
        this.nodes = new Map();
        // Order of node ids, as they first appeared in the stream.
        this.nodeOrder = [];
        this.isRunning = false;
        this.currentNodeId = null;
        this.isNearBottom = true;
    }

    render() {
        this.container.innerHTML = `
            <div class="trace-panel">
                <div class="trace-header">
                    <h3>Live Trace</h3>
                    <div class="trace-banner" id="trace-banner-${this.runId}" style="display: none;">
                        <span class="trace-banner-dot"></span>
                        <span class="trace-banner-label">Running</span>
                        <span class="trace-banner-node" id="trace-banner-node-${this.runId}"></span>
                        <span class="trace-banner-elapsed" id="trace-banner-elapsed-${this.runId}">0s</span>
                    </div>
                </div>
                <div class="trace-feed" id="trace-feed-${this.runId}">
                    <div class="trace-empty">Waiting for workflow to start…</div>
                </div>
            </div>
        `;
        this.feedEl = document.getElementById(`trace-feed-${this.runId}`);
        this.bannerEl = document.getElementById(`trace-banner-${this.runId}`);
        this.bannerNodeEl = document.getElementById(`trace-banner-node-${this.runId}`);
        this.bannerElapsedEl = document.getElementById(`trace-banner-elapsed-${this.runId}`);
        this._setupScrollTracking();
        // Note: the SSE endpoint (/api/workflows/{id}/events) replays the
        // persisted event log on connect, so TracePanel automatically gets
        // history without a separate fetch. No _loadHistory call needed.
    }

    _setupScrollTracking() {
        this.feedEl.addEventListener('scroll', () => {
            const { scrollTop, scrollHeight, clientHeight } = this.feedEl;
            // 60px slop — users often stop a hair above the bottom.
            this.isNearBottom = scrollTop + clientHeight >= scrollHeight - 60;
        });
    }

    _scrollToBottomIfNeeded() {
        if (this.isNearBottom) {
            this.feedEl.scrollTop = this.feedEl.scrollHeight;
        }
    }

    /**
     * Main entry point — called from setupLiveUpdates for each SSE event.
     * payload is the parsed NDJSON event with event_type, node_id, metadata.
     */
    handleEvent(payload) {
        if (!payload || !payload.event_type) return;
        const t = payload.event_type;
        switch (t) {
            case 'workflow_started':
                return this._onWorkflowStarted(payload);
            case 'node_started':
                return this._onNodeStarted(payload);
            case 'node_log_line':
                return this._onLogLine(payload);
            case 'node_stream_token':
                return this._onStreamToken(payload);
            case 'channel_updated':
                return this._onChannelUpdated(payload);
            case 'node_completed':
                return this._onNodeTerminal(payload, 'completed');
            case 'node_failed':
                return this._onNodeTerminal(payload, 'failed');
            case 'node_skipped':
                return this._onNodeTerminal(payload, 'skipped');
            case 'node_interrupted':
                return this._onNodeTerminal(payload, 'interrupted');
            case 'node_escalated':
                return this._onNodeTerminal(payload, 'escalated');
            case 'workflow_completed':
            case 'workflow_failed':
            case 'workflow_interrupted':
            case 'workflow_cancelled':
                return this._onWorkflowTerminal(payload, t.replace('workflow_', ''));
            default:
                return;
        }
    }

    _onWorkflowStarted(_payload) {
        this.isRunning = true;
    }

    _ensureNode(nodeId, model, dispatch) {
        if (this.nodes.has(nodeId)) return this.nodes.get(nodeId);

        // Remove "waiting for workflow" placeholder on first real entry.
        const empty = this.feedEl.querySelector('.trace-empty');
        if (empty) empty.remove();

        const card = document.createElement('div');
        card.className = 'trace-card trace-card-running';
        card.dataset.nodeId = nodeId;
        card.innerHTML = `
            <div class="trace-card-head" role="button" tabindex="0">
                <span class="trace-card-indicator"></span>
                <span class="trace-card-name">${escapeHtml(nodeId)}</span>
                <span class="trace-card-meta">${model ? `<span class="trace-card-model">${escapeHtml(model)}</span>` : ''}${dispatch ? `<span class="trace-card-dispatch">${escapeHtml(dispatch)}</span>` : ''}</span>
                <span class="trace-card-elapsed">0s</span>
                <span class="trace-card-toggle">▾</span>
            </div>
            <div class="trace-card-body"></div>
        `;
        this.feedEl.appendChild(card);
        const headEl = card.querySelector('.trace-card-head');
        const bodyEl = card.querySelector('.trace-card-body');
        const elapsedEl = card.querySelector('.trace-card-elapsed');
        const toggleEl = card.querySelector('.trace-card-toggle');

        headEl.addEventListener('click', () => {
            const collapsed = card.classList.toggle('trace-card-collapsed');
            toggleEl.textContent = collapsed ? '▸' : '▾';
        });

        const entry = {
            el: card,
            headEl,
            bodyEl,
            elapsedEl,
            toggleEl,
            startedAt: Date.now(),
            timerHandle: null,
            logLines: 0,
            tokenBuf: '',
            tokenSpan: null,
            status: 'running',
        };
        this.nodes.set(nodeId, entry);
        this.nodeOrder.push(nodeId);
        return entry;
    }

    _onNodeStarted(payload) {
        const nodeId = payload.node_id;
        if (!nodeId) return;
        const entry = this._ensureNode(nodeId, payload.model, payload.dispatch);
        entry.startedAt = this._parseTimestamp(payload.timestamp) || Date.now();
        entry.status = 'running';
        this._startTimer(entry);
        this.currentNodeId = nodeId;
        this._updateBanner();
        this._scrollToBottomIfNeeded();
    }

    _onLogLine(payload) {
        const nodeId = payload.node_id;
        if (!nodeId) return;
        const entry = this._ensureNode(nodeId);
        const meta = payload.metadata || {};
        const line = typeof meta.line === 'string' ? meta.line : '';
        const stream = meta.stream || 'stdout';
        const lineEl = document.createElement('div');
        lineEl.className = `trace-line trace-line-${stream}`;
        lineEl.textContent = line;
        entry.bodyEl.appendChild(lineEl);
        entry.logLines += 1;
        // Cap runaway logs to keep the DOM light — last 2000 lines per node.
        if (entry.logLines > 2000) {
            const first = entry.bodyEl.firstChild;
            if (first) entry.bodyEl.removeChild(first);
        }
        this._scrollToBottomIfNeeded();
    }

    _onStreamToken(payload) {
        const nodeId = payload.node_id;
        if (!nodeId) return;
        const entry = this._ensureNode(nodeId);
        const tok = (payload.metadata && payload.metadata.token) || '';
        if (!tok) return;
        entry.tokenBuf += tok;
        if (!entry.tokenSpan) {
            entry.tokenSpan = document.createElement('pre');
            entry.tokenSpan.className = 'trace-tokens';
            entry.bodyEl.appendChild(entry.tokenSpan);
        }
        entry.tokenSpan.textContent = entry.tokenBuf;
        this._scrollToBottomIfNeeded();
    }

    _onChannelUpdated(payload) {
        // channel_updated events don't always carry a node_id, but
        // writer_node_id in metadata tells us who wrote.
        const meta = payload.metadata || {};
        const writer = meta.writer_node_id || payload.node_id;
        if (!writer || !this.nodes.has(writer)) return;
        const entry = this.nodes.get(writer);
        const chip = document.createElement('div');
        chip.className = 'trace-channel-chip';
        const key = meta.channel_key || '?';
        const value = typeof meta.value === 'string'
            ? meta.value
            : JSON.stringify(meta.value);
        const shortVal = (value || '').slice(0, 120);
        chip.innerHTML = `<span class="trace-channel-arrow">→</span> <code>${escapeHtml(key)}</code> <span class="trace-channel-value">${escapeHtml(shortVal)}${value && value.length > 120 ? '…' : ''}</span>`;
        entry.bodyEl.appendChild(chip);
        this._scrollToBottomIfNeeded();
    }

    _onNodeTerminal(payload, status) {
        const nodeId = payload.node_id;
        if (!nodeId) return;
        const entry = this._ensureNode(nodeId);
        // Dedupe: persisted + live replay can both deliver the same terminal
        // event. Stamping twice would duplicate error banners and toggle
        // classes back and forth.
        if (entry.terminalShown) return;
        entry.terminalShown = true;
        entry.status = status;
        this._stopTimer(entry, payload.duration_ms);
        entry.el.classList.remove('trace-card-running');
        entry.el.classList.add(`trace-card-${status}`);
        // Auto-collapse completed-success to keep the feed skim-friendly;
        // leave failed/escalated/interrupted open so the user sees the error.
        if (status === 'completed' || status === 'skipped') {
            entry.el.classList.add('trace-card-collapsed');
            entry.toggleEl.textContent = '▸';
        }

        const meta = payload.metadata || {};
        if (status === 'failed' && meta.error) {
            const err = document.createElement('div');
            err.className = 'trace-error';
            err.textContent = meta.error;
            entry.bodyEl.appendChild(err);
        } else if (status === 'escalated') {
            const banner = document.createElement('div');
            banner.className = 'trace-escalation';
            // Rich context: plain-English "what happened" + the error line +
            // the prompt/context that failed (truncated) + a direct link to
            // chat the orchestrator. This replaces the old one-liner that
            // left users wondering how to act on the escalation.
            const err = meta.error || '';
            const promptTail = typeof meta.prompt === 'string' ? meta.prompt.slice(-600) : '';
            const stderrTail = typeof meta.stderr_tail === 'string' ? meta.stderr_tail.slice(-400) : '';
            banner.innerHTML = `
                <div class="trace-escalation-title">
                    <strong>⚠ Needs orchestrator help.</strong>
                    This node couldn't complete on its own and is waiting for you to fix it.
                </div>
                ${err ? `
                    <div class="trace-escalation-section">
                        <div class="trace-escalation-label">Error</div>
                        <pre class="trace-escalation-error">${escapeHtml(err)}</pre>
                    </div>` : ''}
                ${stderrTail ? `
                    <details class="trace-escalation-section">
                        <summary class="trace-escalation-label">stderr tail</summary>
                        <pre class="trace-escalation-pre">${escapeHtml(stderrTail)}</pre>
                    </details>` : ''}
                ${promptTail ? `
                    <details class="trace-escalation-section">
                        <summary class="trace-escalation-label">Prompt context</summary>
                        <pre class="trace-escalation-pre">${escapeHtml(promptTail)}</pre>
                    </details>` : ''}
                <div class="trace-escalation-actions">
                    <a class="trace-escalation-chat-btn" href="#/workflow/${encodeURIComponent(this.runId)}/conversation"
                       data-action="open-chat">💬 Talk to orchestrator about this</a>
                </div>
            `;
            entry.bodyEl.appendChild(banner);
            // Wire the chat button to scroll to a workflow-level chat mount
            // if present, otherwise navigate to the conversation page. Doing
            // this with a click handler lets us dispatch a CustomEvent that
            // the run-detail page can listen for.
            const chatBtn = banner.querySelector('.trace-escalation-chat-btn');
            if (chatBtn) {
                chatBtn.addEventListener('click', (ev) => {
                    ev.preventDefault();
                    window.dispatchEvent(new CustomEvent('trace-chat-request', {
                        detail: { runId: this.runId, nodeId, error: err },
                    }));
                });
            }
            this._appendResumeForm(entry, nodeId, 'escalation');
        } else if (status === 'interrupted') {
            const banner = document.createElement('div');
            banner.className = 'trace-interrupt';
            const msg = meta.message || 'Waiting for input';
            banner.innerHTML = `<strong>Paused:</strong> ${escapeHtml(msg)}`;
            entry.bodyEl.appendChild(banner);
            this._appendResumeForm(entry, nodeId, 'interrupt');
        }

        if (this.currentNodeId === nodeId) {
            this.currentNodeId = null;
            this._updateBanner();
        }
        this._scrollToBottomIfNeeded();
    }

    _onWorkflowTerminal(_payload, status) {
        this.isRunning = false;
        this.currentNodeId = null;
        this._updateBanner();
        // Dedupe: the SSE endpoint replays persisted events on connect AND
        // live events can also fire for terminal states. Without this guard
        // we get two "Workflow interrupted" footers.
        if (this._terminalShown) return;
        this._terminalShown = true;
        const footer = document.createElement('div');
        footer.className = `trace-footer trace-footer-${status}`;
        footer.textContent = `Workflow ${status}`;
        this.feedEl.appendChild(footer);
        this._scrollToBottomIfNeeded();
    }

    /**
     * Render a resume form inside a paused node card.
     *
     * @param entry The card entry.
     * @param nodeId Node id (used for the URL).
     * @param kind Either 'interrupt' (approve/reject buttons + optional
     *   comment) or 'escalation' (textarea for a synthesized output).
     *
     * Both call the same endpoint — the server decides how to interpret
     * the resume_value based on the node's current DB status.
     */
    _appendResumeForm(entry, nodeId, kind) {
        const form = document.createElement('form');
        form.className = 'trace-resume-form';
        if (kind === 'interrupt') {
            form.innerHTML = `
                <div class="trace-resume-heading">⏸ This node is waiting for your input.</div>
                <label class="trace-resume-label">Resume value (text, number, or JSON):</label>
                <input class="trace-resume-input" type="text" placeholder="approve" />
                <label class="trace-resume-label">Comment (optional):</label>
                <input class="trace-resume-comment" type="text" placeholder="why…" />
                <div class="trace-resume-btns">
                    <button type="button" data-action="approve" class="trace-resume-approve">Approve</button>
                    <button type="button" data-action="reject" class="trace-resume-reject">Reject</button>
                    <button type="submit" class="trace-resume-submit">Send custom value</button>
                </div>
                <div class="trace-resume-status" aria-live="polite"></div>
            `;
        } else {
            form.innerHTML = `
                <div class="trace-resume-heading">
                    ⚠ <code>${escapeHtml(nodeId)}</code> escalated. Provide a synthesized output below to continue.
                </div>
                <label class="trace-resume-label">
                    Synthesized output (plain text or a JSON object matching the node's schema):
                </label>
                <textarea class="trace-resume-textarea" rows="4"
                    placeholder='e.g. {"ok": true}'></textarea>
                <label class="trace-resume-label">Decided by (optional):</label>
                <input class="trace-resume-comment" type="text" placeholder="you" />
                <div class="trace-resume-btns">
                    <button type="submit" class="trace-resume-submit">Resume with this output</button>
                </div>
                <div class="trace-resume-status" aria-live="polite"></div>
            `;
        }
        entry.bodyEl.appendChild(form);

        const statusEl = form.querySelector('.trace-resume-status');
        const submitResume = async (value, decidedBy, comment) => {
            statusEl.textContent = 'Resuming…';
            try {
                const resp = await fetch(
                    `/api/workflows/${this.runId}/interrupts/${encodeURIComponent(nodeId)}/resume`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            resume_value: value,
                            decided_by: decidedBy || null,
                            comment: comment || null,
                        }),
                    },
                );
                if (!resp.ok) {
                    const body = await resp.text();
                    statusEl.textContent = `Error ${resp.status}: ${body.slice(0, 180)}`;
                    return;
                }
                statusEl.textContent = 'Resumed — watching for completion…';
                // Disable inputs after a successful submit so the user
                // doesn't accidentally fire it twice while the executor spins up.
                form.querySelectorAll('input,textarea,button').forEach((el) => {
                    el.disabled = true;
                });
            } catch (e) {
                statusEl.textContent = `Failed: ${e.message || e}`;
            }
        };

        const flagError = (msg) => {
            statusEl.textContent = msg;
            statusEl.classList.add('trace-resume-status-error');
        };
        const clearError = () => statusEl.classList.remove('trace-resume-status-error');

        if (kind === 'interrupt') {
            const input = form.querySelector('.trace-resume-input');
            const commentEl = form.querySelector('.trace-resume-comment');
            input.addEventListener('input', clearError);
            form.querySelectorAll('button[data-action]').forEach((btn) => {
                btn.addEventListener('click', (ev) => {
                    ev.preventDefault();
                    clearError();
                    const action = btn.dataset.action;
                    submitResume(action, null, commentEl.value);
                });
            });
            form.addEventListener('submit', (ev) => {
                ev.preventDefault();
                const v = (input.value || '').trim();
                if (!v) { flagError('Enter a value, or click Approve / Reject above.'); input.focus(); return; }
                clearError();
                submitResume(v, null, commentEl.value);
            });
        } else {
            const textarea = form.querySelector('.trace-resume-textarea');
            const decidedBy = form.querySelector('.trace-resume-comment');
            textarea.addEventListener('input', clearError);
            form.addEventListener('submit', (ev) => {
                ev.preventDefault();
                const raw = (textarea.value || '').trim();
                if (!raw) { flagError('Type something above — plain text or JSON — before resuming.'); textarea.focus(); return; }
                clearError();
                // Try JSON — lets the user paste an object. Otherwise send
                // the raw text as a string (prompt-runner convention).
                let value;
                try {
                    value = JSON.parse(raw);
                } catch {
                    value = raw;
                }
                submitResume(value, decidedBy.value, null);
            });
        }
    }

    _startTimer(entry) {
        if (entry.timerHandle) return;
        entry.timerHandle = setInterval(() => {
            const secs = Math.max(0, Math.round((Date.now() - entry.startedAt) / 1000));
            entry.elapsedEl.textContent = `${secs}s`;
        }, 500);
    }

    _stopTimer(entry, durationMs) {
        if (entry.timerHandle) {
            clearInterval(entry.timerHandle);
            entry.timerHandle = null;
        }
        const ms = typeof durationMs === 'number'
            ? durationMs
            : (Date.now() - entry.startedAt);
        entry.elapsedEl.textContent = ms < 1000
            ? `${ms}ms`
            : `${(ms / 1000).toFixed(1)}s`;
    }

    _updateBanner() {
        if (this.currentNodeId) {
            this.bannerEl.style.display = '';
            this.bannerNodeEl.textContent = this.currentNodeId;
            const entry = this.nodes.get(this.currentNodeId);
            if (entry) {
                if (this.bannerTimerHandle) clearInterval(this.bannerTimerHandle);
                this.bannerTimerHandle = setInterval(() => {
                    const secs = Math.max(0, Math.round((Date.now() - entry.startedAt) / 1000));
                    this.bannerElapsedEl.textContent = `${secs}s`;
                }, 500);
            }
        } else {
            this.bannerEl.style.display = 'none';
            if (this.bannerTimerHandle) {
                clearInterval(this.bannerTimerHandle);
                this.bannerTimerHandle = null;
            }
        }
    }

    scrollToNode(nodeId) {
        const entry = this.nodes.get(nodeId);
        if (!entry) return;
        // User clicked a node in the DAG — scroll to it and briefly flash it.
        entry.el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        entry.el.classList.add('trace-card-flash');
        setTimeout(() => entry.el.classList.remove('trace-card-flash'), 1500);
    }

    _parseTimestamp(ts) {
        if (!ts) return null;
        const ms = Date.parse(ts);
        return isFinite(ms) ? ms : null;
    }

    // Called by renderRunDetail's lifecycle on route change / re-entry so
    // per-node + banner intervals don't leak across runs.
    destroy() {
        for (const entry of this.nodes.values()) {
            if (entry && entry.timerHandle) {
                clearInterval(entry.timerHandle);
                entry.timerHandle = null;
            }
        }
        if (this.bannerTimerHandle) {
            clearInterval(this.bannerTimerHandle);
            this.bannerTimerHandle = null;
        }
        this.nodes.clear();
        this.nodeOrder = [];
    }
}

// Small helper (dupe of app.js's escapeHtml, kept local so this file can load
// before or after app.js without ordering dependency)
function escapeHtml(s) {
    if (s == null) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

window.TracePanel = TracePanel;

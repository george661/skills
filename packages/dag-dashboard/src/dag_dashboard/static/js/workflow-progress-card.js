/**
 * WorkflowProgressCard — per-node card rendered inline in the unified feed.
 *
 * One instance per workflow node. Ported from the former TracePanel's per-node
 * surfaces: status icon, model/dispatch tags, live elapsed timer, streaming
 * stdout/tokens, completion summary with channel writes folded in, error
 * banners, and the inline resume form for interrupt + escalation states.
 *
 * Mounted by ChatPanel when it sees a `progress_card` message whose nodeId is
 * not already tracked. Receives follow-up SSE events via handleEvent(payload).
 *
 * Usage:
 *   const card = new WorkflowProgressCard({ runId, nodeId, model, dispatch });
 *   card.mount(parentEl);
 *   card.handleEvent({ subtype: 'node_stream_token', payload: { ... } });
 *   card.destroy();
 */

(function (window) {
    'use strict';

    function escapeHtml(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function parseTimestamp(ts) {
        if (!ts) return null;
        const ms = Date.parse(ts);
        return isFinite(ms) ? ms : null;
    }

    class WorkflowProgressCard {
        constructor(opts) {
            this.runId = opts.runId;
            this.nodeId = opts.nodeId;
            this.model = opts.model || '';
            this.dispatch = opts.dispatch || '';
            this.startedAt = Date.now();
            this.timerHandle = null;
            this.logLines = 0;
            this.tokenBuf = '';
            this.tokenSpan = null;
            this.status = 'running';
            this.terminalShown = false;
            this.channelWrites = []; // [{ key, value }]
            this.channelSummaryEl = null;
            this.userExpanded = false;
            this.el = null;
            this._buildEl();
        }

        _buildEl() {
            const card = document.createElement('div');
            card.className = 'workflow-progress-card workflow-progress-card--running';
            card.dataset.nodeId = this.nodeId;
            card.innerHTML = `
                <div class="workflow-progress-card-head" role="button" tabindex="0">
                    <span class="workflow-progress-card-indicator"></span>
                    <span class="workflow-progress-card-name">${escapeHtml(this.nodeId)}</span>
                    <span class="workflow-progress-card-meta">${this.model ? `<span class="workflow-progress-card-model">${escapeHtml(this.model)}</span>` : ''}${this.dispatch ? `<span class="workflow-progress-card-dispatch">${escapeHtml(this.dispatch)}</span>` : ''}</span>
                    <span class="workflow-progress-card-elapsed">0s</span>
                    <span class="workflow-progress-card-toggle">▾</span>
                </div>
                <div class="workflow-progress-card-body"></div>
            `;
            this.el = card;
            this.headEl = card.querySelector('.workflow-progress-card-head');
            this.bodyEl = card.querySelector('.workflow-progress-card-body');
            this.elapsedEl = card.querySelector('.workflow-progress-card-elapsed');
            this.toggleEl = card.querySelector('.workflow-progress-card-toggle');

            this.headEl.addEventListener('click', () => {
                const collapsed = card.classList.toggle('workflow-progress-card--collapsed');
                this.toggleEl.textContent = collapsed ? '▸' : '▾';
                this.userExpanded = !collapsed;
                if (window.NodeScrollBus) {
                    window.NodeScrollBus.trigger(this.nodeId, 'feed');
                }
            });
            this.headEl.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    this.headEl.click();
                }
            });
        }

        mount(parentEl) {
            if (parentEl && this.el) {
                parentEl.appendChild(this.el);
                this._startTimer();
            }
        }

        /**
         * Apply a `progress_card` message to this card.
         */
        handleEvent(msg) {
            const subtype = msg && msg.subtype;
            const payload = (msg && msg.payload) || {};
            const meta = payload.metadata || {};
            switch (subtype) {
                case 'node_started':
                    return this._onStarted(payload, meta);
                case 'node_log_line':
                    return this._onLogLine(meta);
                case 'node_stream_token':
                case 'node_progress':
                    return this._onStreamToken(meta);
                case 'channel_updated':
                    return this._onChannelUpdated(meta);
                case 'node_completed':
                    return this._onTerminal('completed', payload, meta);
                case 'node_failed':
                    return this._onTerminal('failed', payload, meta);
                case 'node_skipped':
                    return this._onTerminal('skipped', payload, meta);
                case 'node_interrupted':
                    return this._onTerminal('interrupted', payload, meta);
                case 'node_escalated':
                    return this._onTerminal('escalated', payload, meta);
                default:
                    return;
            }
        }

        _onStarted(payload, meta) {
            if (!this.model && (payload.model || meta.model)) this.model = payload.model || meta.model;
            if (!this.dispatch && (payload.dispatch || meta.dispatch)) this.dispatch = payload.dispatch || meta.dispatch;
            const ts = parseTimestamp(payload.timestamp);
            if (ts) this.startedAt = ts;
            this.status = 'running';
            this._startTimer();
        }

        _onLogLine(meta) {
            const line = typeof meta.line === 'string' ? meta.line : '';
            const stream = meta.stream || 'stdout';
            const lineEl = document.createElement('div');
            lineEl.className = `workflow-progress-card-line workflow-progress-card-line--${stream}`;
            lineEl.textContent = line;
            this.bodyEl.appendChild(lineEl);
            this.logLines += 1;
            // Cap runaway logs at 2000 lines to keep the DOM light.
            if (this.logLines > 2000) {
                const first = this.bodyEl.firstChild;
                if (first) this.bodyEl.removeChild(first);
            }
        }

        _onStreamToken(meta) {
            const tok = meta.token || '';
            if (!tok) return;
            this.tokenBuf += tok;
            if (!this.tokenSpan) {
                this.tokenSpan = document.createElement('pre');
                this.tokenSpan.className = 'workflow-progress-card-tokens';
                this.bodyEl.appendChild(this.tokenSpan);
            }
            this.tokenSpan.textContent = this.tokenBuf;
        }

        _onChannelUpdated(meta) {
            const key = meta.channel_key || '?';
            const value = typeof meta.value === 'string'
                ? meta.value
                : JSON.stringify(meta.value);
            this.channelWrites.push({ key, value: value || '' });
            const chip = document.createElement('div');
            chip.className = 'workflow-progress-card-channel-chip';
            const shortVal = (value || '').slice(0, 120);
            chip.innerHTML = `<span class="workflow-progress-card-channel-arrow">→</span> <code>${escapeHtml(key)}</code> <span class="workflow-progress-card-channel-value">${escapeHtml(shortVal)}${value && value.length > 120 ? '…' : ''}</span>`;
            this.bodyEl.appendChild(chip);
            if (this.channelSummaryEl) this._renderChannelSummary();
        }

        _onTerminal(status, payload, meta) {
            if (this.terminalShown) return;
            this.terminalShown = true;
            this.status = status;
            this._stopTimer(payload.duration_ms);
            this.el.classList.remove('workflow-progress-card--running');
            this.el.classList.add(`workflow-progress-card--${status}`);

            // Completion summary: compact line stating what was written.
            if (this.channelWrites.length) {
                const summary = document.createElement('div');
                summary.className = 'workflow-progress-card-summary';
                this.channelSummaryEl = summary;
                this._renderChannelSummary();
                this.bodyEl.insertBefore(summary, this.bodyEl.firstChild);
            }

            // Auto-collapse successes to keep the feed skim-friendly. Leave
            // failed/escalated/interrupted open so the user sees the error.
            // Respect an explicit user expand.
            const shouldCollapse = (status === 'completed' || status === 'skipped') && !this.userExpanded;
            if (shouldCollapse) {
                this.el.classList.add('workflow-progress-card--collapsed');
                this.toggleEl.textContent = '▸';
            }

            if (status === 'failed' && meta.error) {
                const err = document.createElement('div');
                err.className = 'workflow-progress-card-error';
                err.textContent = meta.error;
                this.bodyEl.appendChild(err);
            } else if (status === 'escalated') {
                this._appendEscalationBanner(meta);
                this._appendResumeForm('escalation');
            } else if (status === 'interrupted') {
                const banner = document.createElement('div');
                banner.className = 'workflow-progress-card-interrupt';
                const msg = meta.message || 'Waiting for input';
                banner.innerHTML = `<strong>Paused:</strong> ${escapeHtml(msg)}`;
                this.bodyEl.appendChild(banner);
                this._appendResumeForm('interrupt');
            }
        }

        _renderChannelSummary() {
            if (!this.channelSummaryEl) return;
            const keys = this.channelWrites.map((w) => w.key).join(', ');
            this.channelSummaryEl.innerHTML = `<span class="workflow-progress-card-summary-label">wrote:</span> <code>${escapeHtml(keys)}</code>`;
        }

        _appendEscalationBanner(meta) {
            const err = meta.error || '';
            const promptTail = typeof meta.prompt === 'string' ? meta.prompt.slice(-600) : '';
            const stderrTail = typeof meta.stderr_tail === 'string' ? meta.stderr_tail.slice(-400) : '';
            const banner = document.createElement('div');
            banner.className = 'workflow-progress-card-escalation';
            banner.innerHTML = `
                <div class="workflow-progress-card-escalation-title">
                    <strong>⚠ Needs orchestrator help.</strong>
                    This node couldn't complete on its own and is waiting for input below.
                </div>
                ${err ? `
                    <div class="workflow-progress-card-escalation-section">
                        <div class="workflow-progress-card-escalation-label">Error</div>
                        <pre class="workflow-progress-card-escalation-error">${escapeHtml(err)}</pre>
                    </div>` : ''}
                ${stderrTail ? `
                    <details class="workflow-progress-card-escalation-section">
                        <summary class="workflow-progress-card-escalation-label">stderr tail</summary>
                        <pre class="workflow-progress-card-escalation-pre">${escapeHtml(stderrTail)}</pre>
                    </details>` : ''}
                ${promptTail ? `
                    <details class="workflow-progress-card-escalation-section">
                        <summary class="workflow-progress-card-escalation-label">Prompt context</summary>
                        <pre class="workflow-progress-card-escalation-pre">${escapeHtml(promptTail)}</pre>
                    </details>` : ''}
            `;
            this.bodyEl.appendChild(banner);
        }

        _appendResumeForm(kind) {
            const form = document.createElement('form');
            form.className = 'workflow-progress-card-resume-form';
            if (kind === 'interrupt') {
                form.innerHTML = `
                    <div class="workflow-progress-card-resume-heading">⏸ Waiting for your input.</div>
                    <label class="workflow-progress-card-resume-label">Resume value (text, number, or JSON):</label>
                    <input class="workflow-progress-card-resume-input" type="text" placeholder="approve" />
                    <label class="workflow-progress-card-resume-label">Comment (optional):</label>
                    <input class="workflow-progress-card-resume-comment" type="text" placeholder="why…" />
                    <div class="workflow-progress-card-resume-btns">
                        <button type="button" data-action="approve" class="workflow-progress-card-resume-approve">Approve</button>
                        <button type="button" data-action="reject" class="workflow-progress-card-resume-reject">Reject</button>
                        <button type="submit" class="workflow-progress-card-resume-submit">Send custom value</button>
                    </div>
                    <div class="workflow-progress-card-resume-status" aria-live="polite"></div>
                `;
            } else {
                form.innerHTML = `
                    <div class="workflow-progress-card-resume-heading">
                        ⚠ <code>${escapeHtml(this.nodeId)}</code> escalated. Provide a synthesized output below.
                    </div>
                    <label class="workflow-progress-card-resume-label">
                        Synthesized output (plain text or a JSON object matching the node's schema):
                    </label>
                    <textarea class="workflow-progress-card-resume-textarea" rows="4"
                        placeholder='e.g. {"ok": true}'></textarea>
                    <label class="workflow-progress-card-resume-label">Decided by (optional):</label>
                    <input class="workflow-progress-card-resume-comment" type="text" placeholder="you" />
                    <div class="workflow-progress-card-resume-btns">
                        <button type="submit" class="workflow-progress-card-resume-submit">Resume with this output</button>
                    </div>
                    <div class="workflow-progress-card-resume-status" aria-live="polite"></div>
                `;
            }
            this.bodyEl.appendChild(form);

            const statusEl = form.querySelector('.workflow-progress-card-resume-status');
            const submitResume = async (value, decidedBy, comment) => {
                statusEl.textContent = 'Resuming…';
                try {
                    const resp = await fetch(
                        `/api/workflows/${this.runId}/interrupts/${encodeURIComponent(this.nodeId)}/resume`,
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
                    form.querySelectorAll('input,textarea,button').forEach((el) => {
                        el.disabled = true;
                    });
                } catch (e) {
                    statusEl.textContent = `Failed: ${e.message || e}`;
                }
            };

            const flagError = (m) => {
                statusEl.textContent = m;
                statusEl.classList.add('workflow-progress-card-resume-status--error');
            };
            const clearError = () => statusEl.classList.remove('workflow-progress-card-resume-status--error');

            if (kind === 'interrupt') {
                const input = form.querySelector('.workflow-progress-card-resume-input');
                const commentEl = form.querySelector('.workflow-progress-card-resume-comment');
                input.addEventListener('input', clearError);
                form.querySelectorAll('button[data-action]').forEach((btn) => {
                    btn.addEventListener('click', (ev) => {
                        ev.preventDefault();
                        clearError();
                        submitResume(btn.dataset.action, null, commentEl.value);
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
                const textarea = form.querySelector('.workflow-progress-card-resume-textarea');
                const decidedBy = form.querySelector('.workflow-progress-card-resume-comment');
                textarea.addEventListener('input', clearError);
                form.addEventListener('submit', (ev) => {
                    ev.preventDefault();
                    const raw = (textarea.value || '').trim();
                    if (!raw) { flagError('Type something above — plain text or JSON — before resuming.'); textarea.focus(); return; }
                    clearError();
                    let value;
                    try { value = JSON.parse(raw); } catch { value = raw; }
                    submitResume(value, decidedBy.value, null);
                });
            }
        }

        _startTimer() {
            if (this.timerHandle) return;
            this.timerHandle = setInterval(() => {
                const secs = Math.max(0, Math.round((Date.now() - this.startedAt) / 1000));
                this.elapsedEl.textContent = `${secs}s`;
            }, 500);
        }

        _stopTimer(durationMs) {
            if (this.timerHandle) {
                clearInterval(this.timerHandle);
                this.timerHandle = null;
            }
            const ms = typeof durationMs === 'number'
                ? durationMs
                : (Date.now() - this.startedAt);
            this.elapsedEl.textContent = ms < 1000
                ? `${ms}ms`
                : `${(ms / 1000).toFixed(1)}s`;
        }

        scrollIntoViewAndFlash() {
            if (!this.el) return;
            this.el.scrollIntoView({ behavior: 'smooth', block: 'start' });
            this.el.classList.add('workflow-progress-card--flash');
            setTimeout(() => this.el && this.el.classList.remove('workflow-progress-card--flash'), 1500);
        }

        destroy() {
            if (this.timerHandle) {
                clearInterval(this.timerHandle);
                this.timerHandle = null;
            }
            if (this.el && this.el.parentNode) {
                this.el.parentNode.removeChild(this.el);
            }
            this.el = null;
        }
    }

    window.WorkflowProgressCard = WorkflowProgressCard;
})(window);
